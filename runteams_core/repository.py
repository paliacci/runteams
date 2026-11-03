"""Cloud transaction persistence for the RunTeams product kernel.

Only authored documents, immutable releases and runtime facts are stored.
Readiness, compatibility and UI status are derived by services.
"""

from contextlib import contextmanager
import contextvars
import datetime
import hashlib
import json
import sqlite3
from pathlib import Path



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

    def __init__(self, path, *, storage=None):
        from .business_storage import storage_for
        self.path = str(Path(path).resolve())
        self.storage = storage if storage is not None else storage_for(self.path)
        if storage is not None and str(Path(storage.path).resolve()) != self.path:
            raise ValueError("存储路径不匹配")

    def definition_lock(self):
        # The cloud account transaction lock spans every nested domain connection.
        return self.storage.definition_lock()

    @contextmanager
    def connect(self):
        with self.storage.connect() as connection:
            yield connection

    def initialize(self):
        # The device initializes only host execution/security/cache tables.
        return self.storage.initialize()

    def data_epoch(self):
        return self.storage.data_epoch()

    def rotate_data_epoch(self):
        return self.storage.rotate_data_epoch()

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
        # Rebuilding an event append is safe only when this method owns the
        # whole transaction and the server confirmed an optimistic conflict.
        # Unknown commits and caller-owned mutations must never be replayed.
        from .storage_contracts import BusinessCloudConflict
        cloud = getattr(getattr(self, 'storage', None), 'cloud', None)
        owns = connection is None and not (cloud and getattr(cloud.local, 'connection', None))
        for attempt in range(5 if owns else 1):
            try:
                return self._append_event(stream, event_type, data, connection,
                    actor_id=actor_id, correlation_id=correlation_id,
                    source=source, schema_version=schema_version)
            except BusinessCloudConflict:
                if not owns or attempt == 4:
                    raise

    def _append_event(self, stream, event_type, data, connection=None, *, actor_id=None,
                      correlation_id=None, source=None, schema_version=None):
        context = _AUDIT_CONTEXT.get() or {}
        actor_id = actor_id if actor_id is not None else context.get("actor_id")
        correlation_id = (correlation_id if correlation_id is not None
                          else context.get("correlation_id"))
        source = source or context.get("source") or "system"
        schema_version = int(schema_version or 1)
        storage = getattr(self, 'storage', None)
        if hasattr(storage, 'canonical_data'):
            data = storage.canonical_data(data)
        data_json = json.dumps(data, ensure_ascii=False, sort_keys=True,
                               separators=(",", ":"))
        created_at = utc_now()
        target = connection
        owned = None
        if target is None:
            owned = self.connect()
            target = owned.__enter__()
        try:
            if hasattr(target, 'begin_write'):
                target.begin_write()
            # Explicit engineering SQLite adapters need the same allocation
            # serialization that the cloud revision check supplies in product.
            if isinstance(target, sqlite3.Connection) and not target.in_transaction:
                target.execute('BEGIN IMMEDIATE')
            previous_row = target.execute(
                "SELECT (SELECT event_hash FROM events ORDER BY id DESC LIMIT 1),"
                "max(coalesce((SELECT MAX(id) FROM events),0),"
                "coalesce((SELECT seq FROM sqlite_sequence WHERE name='events'),0))+1").fetchone()
            prev_hash, event_id = previous_row[0], previous_row[1]
            # Preserve the evaluator's identity highwater in this snapshot,
            # including restricted execution views that hide unrelated events.
            # Cloud revision comparison rejects concurrent allocations; an
            # unknown commit is never retried by event(). Include the final
            # hash in the INSERT rather than a second remote UPDATE.
            event_hash = self._event_hash(
                event_id=event_id, stream=stream, event_type=event_type,
                data_json=data_json, created_at=created_at, actor_id=actor_id,
                correlation_id=correlation_id, source=source,
                schema_version=schema_version, prev_hash=prev_hash)
            target.execute(
                "INSERT INTO events(id,stream,type,data_json,created_at,actor_id,"
                "correlation_id,source,schema_version,prev_hash,event_hash) "
                "VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                (event_id, stream, event_type, data_json, created_at, actor_id,
                 correlation_id, source, schema_version, prev_hash, event_hash),
            )
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
