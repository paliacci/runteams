"""Library-owned structured assets, revisions and atomic operation receipts.

This store does not compile source, publish cloud assets or grant market rights.
Employee/SDK validators remain responsible for the contents of a source object.
"""
from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import uuid

from .local_library import private_directory

KINDS = frozenset({'employee', 'pipeline', 'skill', 'project'})
MAX_SOURCE_BYTES = 32 * 1024 * 1024
SCHEMA = '''
CREATE TABLE library_meta(library_id TEXT PRIMARY KEY);
CREATE TABLE assets(id TEXT PRIMARY KEY, kind TEXT NOT NULL, head INTEGER NOT NULL);
CREATE TABLE revisions(asset_id TEXT NOT NULL REFERENCES assets(id), revision INTEGER NOT NULL,
 name TEXT NOT NULL, source_json TEXT NOT NULL, sha256 TEXT NOT NULL, created_at TEXT NOT NULL,
 PRIMARY KEY(asset_id,revision));
CREATE TABLE operations(id TEXT PRIMARY KEY, request_sha256 TEXT NOT NULL, receipt_json TEXT NOT NULL);
CREATE TRIGGER immutable_revision_update BEFORE UPDATE ON revisions BEGIN
 SELECT RAISE(ABORT,'Asset revisions are immutable'); END;
CREATE TRIGGER immutable_revision_delete BEFORE DELETE ON revisions BEGIN
 SELECT RAISE(ABORT,'Asset revisions are immutable'); END;
'''


class AssetConflict(ValueError):
    pass


def _uuid(value):
    if not isinstance(value, str) or str(uuid.UUID(value)) != value:
        raise ValueError('Invalid asset or operation identity')
    return value


def _encoded(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True,
                      separators=(',', ':'), allow_nan=False)


def _hash(value):
    return hashlib.sha256(value.encode()).hexdigest()


class LocalAssets:
    def __init__(self, root, library_id, check):
        self.root = Path(root)
        self.library_id = _uuid(library_id)
        self.path = self.root / 'library-assets.sqlite3'
        self.check = check

    def reference(self, asset_id, kind):
        if kind not in KINDS:
            raise ValueError('Unknown local asset kind')
        return {'schema': 'runteams.local-asset/1', 'library_id': self.library_id,
                'id': _uuid(asset_id), 'kind': kind}

    def _reference(self, reference):
        if not isinstance(reference, dict) or set(reference) != {'schema', 'library_id', 'id', 'kind'}:
            raise ValueError('Invalid local asset reference')
        if reference != self.reference(reference['id'], reference['kind']):
            raise PermissionError('资产属于另一份本机资料库。')
        return reference

    @contextmanager
    def _connect(self, *, write=False):
        self.check()
        private_directory(self.root)
        for path in (self.path, Path(str(self.path) + '-wal'), Path(str(self.path) + '-shm')):
            if path.is_symlink():
                raise ValueError('本机资产存储路径无效。')
        try:
            fd = os.open(self.path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        except FileExistsError:
            pass
        else:
            os.close(fd)
        c = sqlite3.connect(self.path, timeout=30)
        c.row_factory = sqlite3.Row
        try:
            c.execute('PRAGMA foreign_keys=ON')
            c.execute('BEGIN IMMEDIATE')
            version = c.execute('PRAGMA user_version').fetchone()[0]
            if version == 0 and not c.execute("SELECT 1 FROM sqlite_master WHERE type='table'").fetchone():
                from .device_schema import execute
                execute(c, SCHEMA)
                c.execute('INSERT INTO library_meta VALUES(?)', (self.library_id,))
                c.execute('PRAGMA user_version=1')
            elif version != 1:
                raise ValueError('本机资产存储格式不受支持。')
            if [row[0] for row in c.execute('SELECT library_id FROM library_meta')] != [self.library_id]:
                raise PermissionError('资产存储属于另一份本机资料库。')
            self.check()
            c.commit()
            if not write:
                c.execute('PRAGMA query_only=ON')
            c.execute('BEGIN IMMEDIATE' if write else 'BEGIN')
            self.check()
            yield c
            self.check()
            c.commit()
        except BaseException:
            c.rollback()
            raise
        finally:
            c.close()

    def create(self, kind, name, source, *, operation_id):
        operation_id = _uuid(operation_id)
        asset_id = str(uuid.uuid5(uuid.UUID(self.library_id), 'create/' + operation_id))
        return self._save(self.reference(asset_id, kind), name, source, 0, operation_id)

    def save(self, reference, name, source, *, expected_revision, operation_id):
        if type(expected_revision) is not int or expected_revision < 1:
            raise ValueError('保存资产需要明确的当前修订。')
        return self._save(self._reference(reference), name, source,
                          expected_revision, _uuid(operation_id))

    def _save(self, reference, name, source, expected_revision, operation_id):
        if (not isinstance(name, str) or not 1 <= len(name.strip()) <= 120
                or any(ord(char) < 32 for char in name) or not isinstance(source, dict)):
            raise ValueError('资产名称或源码无效。')
        source_json = _encoded(source)
        if len(source_json.encode()) > MAX_SOURCE_BYTES:
            raise ValueError('资产源码超过本机存储限制。')
        request = _encoded({'reference': reference, 'name': name, 'source': source,
                            'expected_revision': expected_revision})
        digest = _hash(_encoded({'name': name, 'source': source}))
        with self._connect(write=True) as c:
            existing = c.execute('SELECT * FROM operations WHERE id=?', (operation_id,)).fetchone()
            if existing:
                if existing['request_sha256'] != _hash(request):
                    raise AssetConflict('同一操作不能保存不同的资产内容。')
                return json.loads(existing['receipt_json'])
            head = c.execute('SELECT * FROM assets WHERE id=?', (reference['id'],)).fetchone()
            if (head is None and expected_revision != 0) or (head is not None and
                    (head['head'] != expected_revision or head['kind'] != reference['kind'])):
                raise AssetConflict('资产已变化，请重新读取后保存。')
            revision = expected_revision + 1
            if head is None:
                c.execute('INSERT INTO assets VALUES(?,?,?)', (reference['id'], reference['kind'], revision))
            else:
                c.execute('UPDATE assets SET head=? WHERE id=?', (revision, reference['id']))
            c.execute('INSERT INTO revisions VALUES(?,?,?,?,?,?)',
                      (reference['id'], revision, name, source_json, digest,
                       datetime.now(timezone.utc).isoformat()))
            receipt = {'reference': reference, 'revision': revision, 'sha256': digest,
                       'operation_id': operation_id}
            c.execute('INSERT INTO operations VALUES(?,?,?)',
                      (operation_id, _hash(request), _encoded(receipt)))
            return receipt

    def get(self, reference, *, revision=None):
        reference = self._reference(reference)
        if revision is not None and (type(revision) is not int or revision < 1):
            raise ValueError('Invalid revision')
        with self._connect() as c:
            head = c.execute('SELECT * FROM assets WHERE id=?', (reference['id'],)).fetchone()
            if head is None or head['kind'] != reference['kind']:
                raise KeyError('本机资产不存在。')
            row = c.execute('SELECT * FROM revisions WHERE asset_id=? AND revision=?',
                            (reference['id'], revision or head['head'])).fetchone()
            if row is None:
                raise KeyError('本机资产修订不存在。')
            source = json.loads(row['source_json'])
            if _hash(_encoded({'name': row['name'], 'source': source})) != row['sha256']:
                raise ValueError('本机资产内容校验失败。')
            return {'reference': reference, 'revision': row['revision'], 'name': row['name'],
                    'source': source, 'sha256': row['sha256'], 'created_at': row['created_at']}

    def list(self, *, kind=None, limit=100, after=''):
        if kind is not None and kind not in KINDS:
            raise ValueError('Unknown local asset kind')
        if type(limit) is not int or not 1 <= limit <= 1000:
            raise ValueError('Invalid asset page size')
        if after:
            _uuid(after)
        with self._connect() as c:
            rows = c.execute('SELECT a.*,r.name,r.sha256 FROM assets a JOIN revisions r '
                'ON r.asset_id=a.id AND r.revision=a.head WHERE a.id>? '
                'AND (? IS NULL OR a.kind=?) ORDER BY a.id LIMIT ?',
                (after, kind, kind, limit + 1)).fetchall()
            items = [{'reference': self.reference(row['id'], row['kind']), 'revision': row['head'],
                      'name': row['name'], 'sha256': row['sha256']} for row in rows[:limit]]
            return {'items': items, 'next_after': rows[limit - 1]['id'] if len(rows) > limit else None}
