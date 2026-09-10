"""SQLite persistence for the RunTeams product kernel.

Only authored documents, immutable releases and runtime facts are stored.
Readiness, compatibility and UI status are derived by services.
"""

from contextlib import contextmanager
import contextvars
import datetime
import hashlib
import json
import sqlite3


SCHEMA = """
CREATE TABLE IF NOT EXISTS packages(
  id INTEGER PRIMARY KEY, key TEXT NOT NULL UNIQUE, source_json TEXT NOT NULL,
  active_revision_id INTEGER, created_at TEXT NOT NULL, updated_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS package_revisions(
  id INTEGER PRIMARY KEY, package_id INTEGER NOT NULL REFERENCES packages(id),
  version INTEGER NOT NULL, digest TEXT NOT NULL, manifest_json TEXT NOT NULL,
  blob_ref TEXT NOT NULL, created_at TEXT NOT NULL,
  UNIQUE(package_id,version), UNIQUE(package_id,digest));
CREATE TABLE IF NOT EXISTS employees(
  id INTEGER PRIMARY KEY, name TEXT NOT NULL, avatar TEXT NOT NULL DEFAULT 'a1',
  draft_json TEXT NOT NULL,
  active_release_id INTEGER, created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
  trashed_at TEXT);
CREATE TABLE IF NOT EXISTS employee_releases(
  id INTEGER PRIMARY KEY, employee_id INTEGER NOT NULL REFERENCES employees(id),
  version INTEGER NOT NULL, digest TEXT NOT NULL, snapshot_json TEXT NOT NULL,
  created_at TEXT NOT NULL,
  UNIQUE(employee_id,version), UNIQUE(employee_id,digest));
CREATE TABLE IF NOT EXISTS pipelines(
  id INTEGER PRIMARY KEY, name TEXT NOT NULL, definition_json TEXT NOT NULL,
  created_at TEXT NOT NULL, updated_at TEXT NOT NULL, trashed_at TEXT,
  paused_at TEXT);
CREATE TABLE IF NOT EXISTS tasks(
  id INTEGER PRIMARY KEY, pipeline_id INTEGER REFERENCES pipelines(id),
  employee_id INTEGER REFERENCES employees(id),
  start_column_key TEXT,
  opportunity_key TEXT,
  title TEXT NOT NULL, payload_json TEXT NOT NULL, state TEXT NOT NULL,
  created_at TEXT NOT NULL, updated_at TEXT NOT NULL, trashed_at TEXT,
  CHECK ((pipeline_id IS NOT NULL) != (employee_id IS NOT NULL)));
CREATE TABLE IF NOT EXISTS workflow_runs(
  id INTEGER PRIMARY KEY, task_id INTEGER NOT NULL UNIQUE REFERENCES tasks(id),
  state TEXT NOT NULL, available_at TEXT, manual_column_key TEXT,
  cursor_key TEXT,
  snapshot_json TEXT NOT NULL,
  created_at TEXT NOT NULL, updated_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS employee_runs(
  id INTEGER PRIMARY KEY, workflow_run_id INTEGER NOT NULL REFERENCES workflow_runs(id),
  position_key TEXT NOT NULL, employee_release_id INTEGER REFERENCES employee_releases(id),
  attempt INTEGER NOT NULL, state TEXT NOT NULL, input_json TEXT NOT NULL,
  output_json TEXT NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
  UNIQUE(workflow_run_id,position_key,attempt));
CREATE TABLE IF NOT EXISTS artifacts(
  id INTEGER PRIMARY KEY, employee_run_id INTEGER REFERENCES employee_runs(id),
  name TEXT NOT NULL, ref TEXT NOT NULL, meta_json TEXT NOT NULL, created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS events(
  id INTEGER PRIMARY KEY, stream TEXT NOT NULL, type TEXT NOT NULL,
  data_json TEXT NOT NULL, created_at TEXT NOT NULL,
  actor_id TEXT, correlation_id TEXT, source TEXT NOT NULL DEFAULT 'system',
  schema_version INTEGER NOT NULL DEFAULT 1,
  prev_hash TEXT, event_hash TEXT);
CREATE INDEX IF NOT EXISTS idx_events_stream ON events(stream,id);
CREATE INDEX IF NOT EXISTS idx_employee_runs_workflow ON employee_runs(workflow_run_id,id);
"""


def utc_now():
    return datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")


_AUDIT_CONTEXT = contextvars.ContextVar("runteams_audit_context", default={})


def current_audit_context():
    return dict(_AUDIT_CONTEXT.get() or {})


@contextmanager
def audit_context(*, actor_id=None, correlation_id=None, source=None):
    """Temporarily attach request provenance to every event on this thread."""
    current = dict(_AUDIT_CONTEXT.get() or {})
    if actor_id is not None:
        current["actor_id"] = str(actor_id)
    if correlation_id is not None:
        current["correlation_id"] = str(correlation_id)
    if source is not None:
        current["source"] = str(source)
    token = _AUDIT_CONTEXT.set(current)
    try:
        yield current
    finally:
        _AUDIT_CONTEXT.reset(token)


class Repository:
    audit_context = staticmethod(audit_context)
    current_audit_context = staticmethod(current_audit_context)

    def __init__(self, path):
        self.path = str(path)

    @contextmanager
    def connect(self):
        connection = sqlite3.connect(self.path, timeout=30)
        connection.row_factory = sqlite3.Row
        try:
            connection.execute("PRAGMA foreign_keys=ON")
            connection.execute("PRAGMA busy_timeout=30000")
            with connection:
                yield connection
        finally:
            connection.close()

    def initialize(self):
        with self.connect() as connection:
            connection.executescript(SCHEMA)
            self._migrate_audit_events(connection)
            self._migrate_artifact_owner(connection)
            pipeline_columns = {
                row[1] for row in connection.execute("PRAGMA table_info(pipelines)")
            }
            if "trashed_at" not in pipeline_columns:
                connection.execute("ALTER TABLE pipelines ADD COLUMN trashed_at TEXT")
            if "paused_at" not in pipeline_columns:
                connection.execute("ALTER TABLE pipelines ADD COLUMN paused_at TEXT")
            employee_columns = {
                row[1] for row in connection.execute("PRAGMA table_info(employees)")
            }
            if "trashed_at" not in employee_columns:
                connection.execute("ALTER TABLE employees ADD COLUMN trashed_at TEXT")
            if "avatar" not in employee_columns:
                connection.execute(
                    "ALTER TABLE employees ADD COLUMN avatar TEXT NOT NULL DEFAULT 'a1'")
            artifact_columns = {
                row[1] for row in connection.execute("PRAGMA table_info(artifacts)")
            }
            if "trashed_at" not in artifact_columns:
                connection.execute("ALTER TABLE artifacts ADD COLUMN trashed_at TEXT")
            workflow_columns = {
                row[1] for row in connection.execute("PRAGMA table_info(workflow_runs)")
            }
            if "manual_column_key" not in workflow_columns:
                connection.execute(
                    "ALTER TABLE workflow_runs ADD COLUMN manual_column_key TEXT")
            if "cursor_key" not in workflow_columns:
                connection.execute(
                    "ALTER TABLE workflow_runs ADD COLUMN cursor_key TEXT")
            task_columns = {
                row[1] for row in connection.execute("PRAGMA table_info(tasks)")
            }
            if "trashed_at" not in task_columns:
                connection.execute("ALTER TABLE tasks ADD COLUMN trashed_at TEXT")
            if "start_column_key" not in task_columns:
                connection.execute("ALTER TABLE tasks ADD COLUMN start_column_key TEXT")
            if "start_position_key" in task_columns:
                connection.execute(
                    "UPDATE tasks SET start_column_key=start_position_key "
                    "WHERE start_column_key IS NULL")
        self._migrate_trial_targets()
        self._migrate_task_start_column()
        with self.connect() as connection:
            task_columns = {row[1] for row in connection.execute("PRAGMA table_info(tasks)")}
            if "opportunity_key" not in task_columns:
                connection.execute("ALTER TABLE tasks ADD COLUMN opportunity_key TEXT")
            self._migrate_opportunity_keys(connection)

    @staticmethod
    def _event_hash(*, event_id, stream, event_type, data_json, created_at,
                    actor_id, correlation_id, source, schema_version, prev_hash):
        """Hash the canonical event envelope for tamper-evident local history."""
        payload = {
            "id": int(event_id), "stream": str(stream), "type": str(event_type),
            "data_json": str(data_json), "created_at": str(created_at),
            "actor_id": actor_id, "correlation_id": correlation_id,
            "source": str(source or "system"),
            "schema_version": int(schema_version or 1), "prev_hash": prev_hash,
        }
        encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True,
                             separators=(",", ":")).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()

    @classmethod
    def _migrate_audit_events(cls, connection):
        """Add the durable audit envelope and backfill legacy events once."""
        columns = {row[1] for row in connection.execute("PRAGMA table_info(events)")}
        additions = (
            ("actor_id", "TEXT"),
            ("correlation_id", "TEXT"),
            ("source", "TEXT NOT NULL DEFAULT 'system'"),
            ("schema_version", "INTEGER NOT NULL DEFAULT 1"),
            ("prev_hash", "TEXT"),
            ("event_hash", "TEXT"),
        )
        for name, definition in additions:
            if name not in columns:
                connection.execute("ALTER TABLE events ADD COLUMN {} {}".format(
                    name, definition))
        connection.execute(
            "CREATE INDEX IF NOT EXISTS idx_events_correlation ON events(correlation_id,id)")
        previous = None
        rows = connection.execute(
            "SELECT id,stream,type,data_json,created_at,actor_id,correlation_id,"
            "source,schema_version,prev_hash,event_hash FROM events ORDER BY id"
        ).fetchall()
        for row in rows:
            # Rebuild the chain only for legacy/malformed rows.  This keeps the
            # migration idempotent while making old history verifiable.
            expected_prev = previous
            event_hash = cls._event_hash(
                event_id=row["id"], stream=row["stream"], event_type=row["type"],
                data_json=row["data_json"], created_at=row["created_at"],
                actor_id=row["actor_id"], correlation_id=row["correlation_id"],
                source=row["source"] or "system", schema_version=row["schema_version"] or 1,
                prev_hash=expected_prev)
            if row["prev_hash"] != expected_prev or row["event_hash"] != event_hash:
                connection.execute(
                    "UPDATE events SET prev_hash=?,event_hash=? WHERE id=?",
                    (expected_prev, event_hash, row["id"]))
            previous = event_hash

    @staticmethod
    def _migrate_artifact_owner(connection):
        """Allow authored documents to exist without manufacturing an employee run.

        Employee-produced artifacts keep their existing foreign key.  Agent Chat
        documents reuse the same immutable artifact/revision store with a NULL
        employee_run_id and identify their source in meta_json.  SQLite cannot
        drop NOT NULL in place, so rebuild only when an older database still has
        the strict column.
        """
        columns = connection.execute("PRAGMA table_info(artifacts)").fetchall()
        owner = next((row for row in columns if row[1] == "employee_run_id"), None)
        if owner is None or not int(owner[3]):
            return
        connection.execute("ALTER TABLE artifacts RENAME TO artifacts_owned_legacy")
        connection.execute(
            "CREATE TABLE artifacts(" 
            "id INTEGER PRIMARY KEY, employee_run_id INTEGER REFERENCES employee_runs(id),"
            "name TEXT NOT NULL, ref TEXT NOT NULL, meta_json TEXT NOT NULL,"
            "created_at TEXT NOT NULL, trashed_at TEXT)"
        )
        legacy_columns = {row[1] for row in connection.execute(
            "PRAGMA table_info(artifacts_owned_legacy)")}
        trashed = ",trashed_at" if "trashed_at" in legacy_columns else ""
        select_trashed = ",trashed_at" if trashed else ",NULL"
        connection.execute(
            "INSERT INTO artifacts(id,employee_run_id,name,ref,meta_json,created_at,trashed_at) "
            "SELECT id,employee_run_id,name,ref,meta_json,created_at{} "
            "FROM artifacts_owned_legacy".format(select_trashed))
        connection.execute("DROP TABLE artifacts_owned_legacy")

    @staticmethod
    def _migrate_opportunity_keys(connection):
        """Promote JSON identities to a compact indexed task field.

        Historical duplicates are retained as records, but only one canonical
        task per owner/key receives the indexed value.  The payload is never
        rewritten, so the complete audit trail remains available.
        """
        legacy = {row[1] for row in connection.execute(
            "PRAGMA table_info(opportunity_identities)")}
        if "opportunity_key" not in {row[1] for row in connection.execute(
                "PRAGMA table_info(tasks)")}:  # defensive for unusual legacy DBs
            return
        connection.execute("UPDATE tasks SET opportunity_key=NULL")
        if legacy:
            rows = connection.execute(
                "SELECT owner_type,owner_id,opportunity_key,task_id "
                "FROM opportunity_identities ORDER BY id").fetchall()
            for row in rows:
                connection.execute("UPDATE tasks SET opportunity_key=? WHERE id=?",
                                   (row["opportunity_key"], row["task_id"]))
        else:
            rows = connection.execute(
                "SELECT id,pipeline_id,employee_id,trashed_at,payload_json "
                "FROM tasks WHERE json_extract(payload_json,'$.context.opportunity_key') "
                "IS NOT NULL ORDER BY (trashed_at IS NOT NULL), id").fetchall()
            seen = set()
            for row in rows:
                owner_type = "pipeline" if row["pipeline_id"] is not None else "employee"
                owner_id = row["pipeline_id"] if row["pipeline_id"] is not None else row["employee_id"]
                try:
                    key = str(json.loads(row["payload_json"] or "{}").get("context", {}).get(
                        "opportunity_key") or "").strip()[:240]
                except (TypeError, ValueError, json.JSONDecodeError):
                    key = ""
                identity = (owner_type, int(owner_id or 0), key)
                if key and owner_id and identity not in seen:
                    connection.execute("UPDATE tasks SET opportunity_key=? WHERE id=?",
                                       (key, int(row["id"])))
                    seen.add(identity)
        if legacy:
            connection.execute("DROP TABLE opportunity_identities")
        connection.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS idx_tasks_employee_opportunity "
            "ON tasks(employee_id,opportunity_key) WHERE employee_id IS NOT NULL "
            "AND opportunity_key IS NOT NULL")
        connection.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS idx_tasks_pipeline_opportunity "
            "ON tasks(pipeline_id,opportunity_key) WHERE pipeline_id IS NOT NULL "
            "AND opportunity_key IS NOT NULL")
    def _migrate_trial_targets(self):
        """Widen the two existing ownership references without adding business tables."""
        connection = sqlite3.connect(self.path, timeout=30)
        try:
            connection.execute("PRAGMA foreign_keys=OFF")
            task_columns = {row[1]: row for row in connection.execute(
                "PRAGMA table_info(tasks)")}
            run_columns = {row[1]: row for row in connection.execute(
                "PRAGMA table_info(employee_runs)")}
            needs_tasks = ("employee_id" not in task_columns or
                           bool(task_columns.get("pipeline_id", [None, None, None, 0])[3]))
            needs_runs = bool(run_columns.get("employee_release_id", [None, None, None, 0])[3])
            if not needs_tasks and not needs_runs:
                return
            with connection:
                if needs_runs:
                    connection.execute("""
                        CREATE TABLE employee_runs_new(
                          id INTEGER PRIMARY KEY,
                          workflow_run_id INTEGER NOT NULL REFERENCES workflow_runs(id),
                          position_key TEXT NOT NULL,
                          employee_release_id INTEGER REFERENCES employee_releases(id),
                          attempt INTEGER NOT NULL, state TEXT NOT NULL,
                          input_json TEXT NOT NULL, output_json TEXT NOT NULL,
                          created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
                          UNIQUE(workflow_run_id,position_key,attempt))
                    """)
                    connection.execute(
                        "INSERT INTO employee_runs_new SELECT * FROM employee_runs")
                    connection.execute("DROP TABLE employee_runs")
                    connection.execute("ALTER TABLE employee_runs_new RENAME TO employee_runs")
                if needs_tasks:
                    connection.execute("""
                        CREATE TABLE tasks_new(
                          id INTEGER PRIMARY KEY,
                          pipeline_id INTEGER REFERENCES pipelines(id),
                          employee_id INTEGER REFERENCES employees(id),
                          start_column_key TEXT,
                          opportunity_key TEXT,
                          title TEXT NOT NULL, payload_json TEXT NOT NULL,
                          state TEXT NOT NULL, created_at TEXT NOT NULL,
                          updated_at TEXT NOT NULL, trashed_at TEXT,
                          CHECK ((pipeline_id IS NOT NULL) != (employee_id IS NOT NULL)))
                    """)
                    employee_expression = "employee_id" if "employee_id" in task_columns else "NULL"
                    column_expression = ("start_column_key"
                                         if "start_column_key" in task_columns else "NULL")
                    connection.execute(
                        "INSERT INTO tasks_new(id,pipeline_id,employee_id,start_column_key,opportunity_key,title,payload_json,state,created_at,updated_at,trashed_at) "
                        "SELECT id,pipeline_id,{},{},{},title,payload_json,state,created_at,updated_at,{} FROM tasks".format(
                            employee_expression, column_expression,
                            "opportunity_key" if "opportunity_key" in task_columns else "NULL",
                            "trashed_at" if "trashed_at" in task_columns else "NULL"))
                    connection.execute("DROP TABLE tasks")
                    connection.execute("ALTER TABLE tasks_new RENAME TO tasks")
                connection.execute(
                    "CREATE INDEX IF NOT EXISTS idx_employee_runs_workflow "
                    "ON employee_runs(workflow_run_id,id)")
            violations = list(connection.execute("PRAGMA foreign_key_check"))
            if violations:
                raise RuntimeError("核心数据库迁移后存在无效引用")
        finally:
            connection.close()

    def _migrate_task_start_column(self):
        """Replace the short-lived position-only field with one board-column field."""
        connection = sqlite3.connect(self.path, timeout=30)
        try:
            columns = {row[1] for row in connection.execute("PRAGMA table_info(tasks)")}
            if "start_position_key" not in columns:
                return
            opportunity_expression = "opportunity_key" if "opportunity_key" in columns else "NULL"
            connection.execute("PRAGMA foreign_keys=OFF")
            with connection:
                connection.execute("""
                    CREATE TABLE tasks_column_new(
                      id INTEGER PRIMARY KEY,
                      pipeline_id INTEGER REFERENCES pipelines(id),
                      employee_id INTEGER REFERENCES employees(id),
                      start_column_key TEXT,
                      opportunity_key TEXT,
                      title TEXT NOT NULL, payload_json TEXT NOT NULL,
                      state TEXT NOT NULL, created_at TEXT NOT NULL,
                      updated_at TEXT NOT NULL, trashed_at TEXT,
                      CHECK ((pipeline_id IS NOT NULL) != (employee_id IS NOT NULL)))
                """)
                connection.execute(
                    "INSERT INTO tasks_column_new(id,pipeline_id,employee_id,start_column_key,opportunity_key,title,payload_json,state,created_at,updated_at,trashed_at) "
                    "SELECT id,pipeline_id,employee_id,COALESCE(start_column_key,start_position_key),{},title,payload_json,state,created_at,updated_at,trashed_at FROM tasks".format(opportunity_expression))
                connection.execute("DROP TABLE tasks")
                connection.execute("ALTER TABLE tasks_column_new RENAME TO tasks")
            violations = list(connection.execute("PRAGMA foreign_key_check"))
            if violations:
                raise RuntimeError("任务起始列迁移后存在无效引用")
        finally:
            connection.close()

    @staticmethod
    def decode(row, *json_fields):
        if row is None:
            return None
        item = dict(row)
        for field in json_fields:
            item[field] = json.loads(item[field])
        return item

    def event(self, stream, event_type, data, connection=None, *, actor_id=None,
              correlation_id=None, source=None, schema_version=None):
        context = _AUDIT_CONTEXT.get() or {}
        actor_id = actor_id if actor_id is not None else context.get("actor_id")
        correlation_id = (correlation_id if correlation_id is not None
                          else context.get("correlation_id"))
        source = source or context.get("source") or "system"
        schema_version = int(schema_version or 1)
        data_json = json.dumps(data, ensure_ascii=False, sort_keys=True,
                               separators=(",", ":"))
        created_at = utc_now()
        target = connection
        owned = None
        if target is None:
            owned = self.connect()
            target = owned.__enter__()
        try:
            previous_row = target.execute(
                "SELECT event_hash FROM events ORDER BY id DESC LIMIT 1").fetchone()
            prev_hash = previous_row[0] if previous_row else None
            # SQLite assigns the id during INSERT, so reserve it inside the same
            # transaction before calculating the hash.
            cursor = target.execute(
                "INSERT INTO events(stream,type,data_json,created_at,actor_id,"
                "correlation_id,source,schema_version,prev_hash,event_hash) "
                "VALUES(?,?,?,?,?,?,?,?,?,NULL)",
                (stream, event_type, data_json, created_at, actor_id,
                 correlation_id, source, schema_version, prev_hash),
            )
            event_id = cursor.lastrowid
            event_hash = self._event_hash(
                event_id=event_id, stream=stream, event_type=event_type,
                data_json=data_json, created_at=created_at, actor_id=actor_id,
                correlation_id=correlation_id, source=source,
                schema_version=schema_version, prev_hash=prev_hash)
            target.execute("UPDATE events SET event_hash=? WHERE id=?",
                           (event_hash, event_id))
            return event_id
        except BaseException as exc:
            if owned is not None:
                owned.__exit__(type(exc), exc, exc.__traceback__)
                owned = None
            raise
        finally:
            if owned is not None:
                owned.__exit__(None, None, None)

    def events(self, stream):
        with self.connect() as connection:
            rows = connection.execute(
                "SELECT * FROM events WHERE stream=? ORDER BY id", (stream,)).fetchall()
        return [self.decode(row, "data_json") for row in rows]

    def events_for_streams(self, streams):
        streams = list(dict.fromkeys(str(stream) for stream in (streams or []) if stream))
        if not streams:
            return []
        placeholders = ",".join("?" for _ in streams)
        with self.connect() as connection:
            rows = connection.execute(
                "SELECT * FROM events WHERE stream IN ({}) ORDER BY id".format(placeholders),
                streams).fetchall()
        return [self.decode(row, "data_json") for row in rows]

    def events_all(self):
        """Return the append-only ledger in event-id order.

        This is intentionally a small, read-only primitive for audit
        reconstruction.  It is used only when an entity row has been purged
        and its surviving tombstone events are the only source of identity.
        """
        with self.connect() as connection:
            rows = connection.execute("SELECT * FROM events ORDER BY id").fetchall()
        return [self.decode(row, "data_json") for row in rows]

    def verify_event_chain(self):
        """Return a compact integrity report for the append-only event ledger."""
        with self.connect() as connection:
            rows = connection.execute(
                "SELECT id,stream,type,data_json,created_at,actor_id,correlation_id,"
                "source,schema_version,prev_hash,event_hash FROM events ORDER BY id"
            ).fetchall()
        previous = None
        invalid = []
        for row in rows:
            expected = self._event_hash(
                event_id=row["id"], stream=row["stream"], event_type=row["type"],
                data_json=row["data_json"], created_at=row["created_at"],
                actor_id=row["actor_id"], correlation_id=row["correlation_id"],
                source=row["source"] or "system", schema_version=row["schema_version"] or 1,
                prev_hash=previous)
            if row["prev_hash"] != previous or row["event_hash"] != expected:
                invalid.append(int(row["id"]))
            previous = row["event_hash"]
        return {"valid": not invalid, "event_count": len(rows), "invalid_ids": invalid}
