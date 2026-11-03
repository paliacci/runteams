"""Atomic device source revisions. Original imports remain immutable.

Only the head is mutable. Unpublished snapshots left by a killed writer are
invisible; retries use the original operation identity and exact input.
"""
from contextlib import contextmanager
from datetime import datetime, timezone
import fcntl
import hashlib
import os
from pathlib import Path
import re
import shutil
import stat
import tempfile

from runteams_core.authoring.creator_contracts import canonical, digest, source_files, strict_json, tree
from runteams_core.authoring.source.creator_local_source import _read, _sync
from runteams_core.authoring.source.creator_source_archive import inspect, pack

REV = re.compile(r'r-[a-f0-9]{64}')


class SourceConflict(ValueError):
    pass


class Revisions:
    def __init__(self, store, identity):
        self.store, self.identity = store, identity
        self.original = store.describe(identity)
        self.root = store._directory(identity)

    @contextmanager
    def locked(self):
        self.store.check_scope()
        fd = os.open(self.root / '.edit-lock', os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW | os.O_NONBLOCK, 0o600)
        try:
            if not stat.S_ISREG(os.fstat(fd).st_mode) or os.fstat(fd).st_nlink != 1:
                raise ValueError('源码锁文件无效。')
            fcntl.flock(fd, fcntl.LOCK_EX)
            self.store.check_scope()
            yield
            self.store.check_scope()
        finally:
            os.close(fd)

    def _head(self):
        try:
            head = strict_json(_read(self.root / 'head.json', 1024))
        except FileNotFoundError:
            return self.identity
        if not isinstance(head, dict) or set(head) != {'revision'} or not REV.fullmatch(str(head['revision'])):
            raise ValueError('源码修订记录无效。')
        return head['revision']

    def _revision(self, revision):
        if not isinstance(revision, str) or not REV.fullmatch(revision):
            raise ValueError('源码修订无效。')
        directory = self.root / 'revisions' / revision
        if directory.parent.is_symlink() or directory.is_symlink():
            raise ValueError('源码修订目录无效。')
        meta = strict_json(_read(directory / 'revision.json', 1024 * 1024))
        if (not isinstance(meta, dict) or set(meta) != {'revision','parent','request_sha256','source','archive_sha256','created_at'} or
                meta.get('revision') != revision or not isinstance(meta.get('source'), dict) or
                not isinstance(meta.get('parent'), str) or
                meta['parent'] != self.identity and not REV.fullmatch(meta['parent']) or
                any(not isinstance(meta.get(k), str) or not re.fullmatch('[a-f0-9]{64}',meta[k])
                    for k in ('request_sha256','archive_sha256')) or not isinstance(meta.get('created_at'),str)):
            raise ValueError('源码修订记录无效。')
        datetime.fromisoformat(meta['created_at'])
        raw = _read(directory / 'source.zip', 33 * 1024 * 1024)
        if hashlib.sha256(raw).hexdigest() != meta.get('archive_sha256'):
            raise ValueError('源码修订校验失败，原版本已保留。')
        files = inspect(raw)
        if tree(files) != meta['source']:
            raise ValueError('源码修订内容已变化。')
        return meta, files

    def _files(self, revision):
        return self.store.files(self.identity) if revision == self.identity else self._revision(revision)[1]

    def current(self):
        with self.locked():
            revision = self._head()
            files = self._files(revision)
            return {'revision': revision, 'source': tree(files), 'original_revision': self.identity}

    def files(self):
        with self.locked():
            return self._files(self._head())

    def files_at(self, revision):
        with self.locked():
            if revision != self.identity and revision not in [m['revision'] for m in self._history()]:
                raise SourceConflict('源码基线已变化，请核对最新源码。')
            return self._files(revision)

    def export(self, expected):
        """Capture only the selected saved head; work and journals are siblings."""
        with self.locked():
            if expected != self._head():
                raise SourceConflict('源码已有更新，请刷新后再导出。')
            files = self._files(expected)
            raw = pack(files)
            inspect(raw)
            self.store.check_scope()
            return raw

    def _history(self):
        revision, result, seen = self._head(), [], set()
        while revision != self.identity:
            if revision in seen:
                raise ValueError('源码修订链无效。')
            seen.add(revision)
            meta, _ = self._revision(revision)
            result.append(meta)
            revision = meta['parent']
        return result

    def history(self):
        with self.locked():
            return {'items': [{k: m[k] for k in ('revision', 'parent', 'created_at', 'source')} for m in self._history()],
                    'original_revision': self.identity, 'revision': self._head()}

    def receipt(self, operation_key):
        if not isinstance(operation_key, str) or not re.fullmatch(r'[A-Za-z0-9_-]{8,128}', operation_key):
            raise ValueError('源码保存标识无效。')
        revision = 'r-' + hashlib.sha256(operation_key.encode()).hexdigest()
        with self.locked():
            previous = next((m for m in self._history() if m['revision'] == revision), None)
            return {'state': 'confirmed', 'result': {'revision': revision, 'source': previous['source'],
                    'original_revision': self.identity}} if previous else {'state': 'unknown'}

    def commit(self, files, base, operation_key):
        files = source_files(files)
        if not isinstance(operation_key, str) or not re.fullmatch(r'[A-Za-z0-9_-]{8,128}', operation_key):
            raise ValueError('源码保存标识无效。')
        revision = 'r-' + hashlib.sha256(operation_key.encode()).hexdigest()
        source = tree(files)
        request_hash = digest({'base': base, 'source': source})
        with self.locked():
            for previous in self._history():
                if previous['revision'] == revision:
                    if previous['request_sha256'] != request_hash:
                        raise SourceConflict('这次保存的内容已变化，请保留编辑后重新核对。')
                    return {'revision': revision, 'source': previous['source'], 'original_revision': self.identity}
            if base != self._head():
                raise SourceConflict('源码已在其他位置更新。当前编辑已保留，请先核对最新源码。')
            from runteams_core.employees.employee_avatars import validate_sources
            validate_sources(files)
            revisions = self.root / 'revisions'
            if revisions.is_symlink():
                raise ValueError('源码修订目录无效。')
            revisions.mkdir(mode=0o700, exist_ok=True)
            destination = revisions / revision
            if destination.exists() or destination.is_symlink():
                previous, _ = self._revision(revision)
                if previous.get('request_sha256') != request_hash:
                    raise SourceConflict('这次保存的内容已变化，请重新核对。')
            else:
                raw = pack(files)
                inspect(raw)  # Include file/directory collision checks before publication.
                meta = {'revision': revision, 'parent': base, 'request_sha256': request_hash,
                        'source': source, 'archive_sha256': hashlib.sha256(raw).hexdigest(),
                        'created_at': datetime.now(timezone.utc).isoformat()}
                stage = Path(tempfile.mkdtemp(prefix='.revision-', dir=self.root))
                try:
                    for name, body in [('source.zip', raw), ('revision.json', canonical(meta))]:
                        with (stage / name).open('xb') as stream:
                            os.chmod(stream.name, 0o600)
                            stream.write(body); stream.flush(); os.fsync(stream.fileno())
                    _sync(stage)
                    self.store.check_scope()
                    os.rename(stage, destination)
                    _sync(revisions)
                finally:
                    if stage.exists():
                        shutil.rmtree(stage)
            fd, name = tempfile.mkstemp(prefix='.head-', dir=self.root)
            try:
                with os.fdopen(fd, 'wb') as stream:
                    stream.write(canonical({'revision': revision})); stream.flush(); os.fsync(stream.fileno())
                self.store.check_scope()
                os.replace(name, self.root / 'head.json')
                _sync(self.root)
            finally:
                if os.path.exists(name):
                    os.unlink(name)
            return {'revision': revision, 'source': source, 'original_revision': self.identity}

    def snapshot(self, destination):
        """Copy only committed reachable revisions, under the same writer lock."""
        with self.locked():
            history = self._history()
            for meta in history:
                revision = meta['revision']
                self._revision(revision)
                target = Path(destination) / 'revisions' / revision
                target.mkdir(mode=0o700, parents=True)
                for name in ('revision.json', 'source.zip'):
                    raw = _read(self.root / 'revisions' / revision / name, 33 * 1024 * 1024)
                    with (target / name).open('xb') as stream:
                        os.chmod(stream.name, 0o600)
                        stream.write(raw); stream.flush(); os.fsync(stream.fileno())
            if history:
                target = Path(destination) / 'head.json'
                target.write_bytes(canonical({'revision': self._head()})); target.chmod(0o600)
            from runteams_core.assets.source_links import LINK
            from runteams_core.assets.source_links import links
            if (self.root/LINK).exists():
                value={'schema':'runteams.employee-links/v1','source_id':self.identity,'employees':links(self.store,self.identity)}
                with (Path(destination)/LINK).open('xb') as stream:
                    os.chmod(stream.name,0o600);stream.write(canonical(value));stream.flush();os.fsync(stream.fileno())
            from runteams_core.authoring.creator_local_authoring import snapshot_work
            snapshot_work(self, destination)
