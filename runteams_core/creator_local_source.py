"""Immutable, device-owned SDK source drafts. No execution or publication.

A source digest identifies bytes, never ownership of a platform employee. Import
does not replace an existing project or confer third-party source permissions.
The loopback handler supplies its captured account scope and isolated checker.
"""
import errno
import hashlib
import os
from pathlib import Path
import re
import shutil
import stat
import tempfile
from datetime import datetime, timezone

from .creator_contracts import MAX_BYTES, CreatorContractError, canonical, strict_json
from .creator_source_archive import inspect

SCHEMA = 'runteams.local-source-draft/1'
HASH = re.compile(r'[a-f0-9]{64}')


def _hash(value):
    if not isinstance(value, str) or not HASH.fullmatch(value):
        raise ValueError('源码标识无效。')
    return value


def _read(path, limit):
    for _ in range(3):
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        with os.fdopen(fd, 'rb') as stream:
            info = os.fstat(stream.fileno())
            # Atomic status replacement may unlink the descriptor between open
            # and fstat. Reopen the current path with all original checks; do
            # not read detached bytes or relax symlink/hard-link restrictions.
            if stat.S_ISREG(info.st_mode) and info.st_nlink == 0:
                continue
            if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_size > limit:
                raise ValueError('本机源码文件无效。')
            body = stream.read(limit + 1)
            if len(body) != info.st_size:
                raise ValueError('本机源码文件已变化。')
            return body
    raise ValueError('本机源码文件持续变化，请稍后重试。')


def _sync(path):
    fd = os.open(path, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


class LocalSources:
    def __init__(self, root, check_scope=lambda: None):
        self.root = Path(root)
        self.check_scope = check_scope
        self.check_scope()
        if any(p.is_symlink() for p in (self.root, *self.root.parents)):
            raise ValueError('本机源码目录无效。')
        self.root.mkdir(mode=0o700, parents=True, exist_ok=True)
        self.root.chmod(0o700)

    def _directory(self, identity):
        path = self.root / _hash(identity)
        if path.is_symlink():
            raise ValueError('本机源码目录无效。')
        return path

    def describe(self, identity, *, verify=True):
        self.check_scope()
        path = self._directory(identity)
        value = strict_json(_read(path / 'draft.json', 1024 * 1024))
        if (not isinstance(value, dict) or value.get('schema') != SCHEMA or value.get('id') != identity or
                not isinstance(value.get('source'), dict) or value['source'].get('sha256') != identity or
                not isinstance(value['source'].get('files'), list) or not 1 <= len(value['source']['files']) <= 500 or
                any(not isinstance(f, dict) or not isinstance(f.get('path'), str) or
                    not isinstance(f.get('sha256'), str) for f in value['source']['files']) or
                not isinstance(value.get('project'), dict) or
                any(not isinstance(value['project'].get(k), str) for k in ('name', 'key', 'version')) or
                not isinstance(value.get('created_at'), str) or
                not isinstance(value.get('archive_sha256'), str) or not HASH.fullmatch(value['archive_sha256']) or
                value.get('scope') != 'device-source-draft' or value.get('published') is not False or
                value.get('cloud_verified') is not False):
            raise ValueError('本机源码记录无效。')
        datetime.fromisoformat(value['created_at'])
        if verify:
            self.archive(identity, metadata=value)
        self.check_scope()
        return value

    def archive(self, identity, *, metadata=None):
        self.check_scope()
        metadata = metadata or self.describe(identity, verify=False)
        raw = _read(self._directory(identity) / 'source.zip', MAX_BYTES + 1024 * 1024)
        if hashlib.sha256(raw).hexdigest() != metadata['archive_sha256']:
            raise ValueError('本机源码校验失败，原记录已保留。请保留原始源码包以便恢复。')
        self.check_scope()
        return raw

    def files(self, identity):
        # Integrity is rechecked before parsing. No archive paths are extracted.
        return inspect(self.archive(identity))

    def list(self, after=None):
        self.check_scope()
        if after is not None:
            _hash(after)
        keys = sorted(p.name for p in self.root.iterdir() if HASH.fullmatch(p.name))
        keys = [k for k in keys if after is None or k > after]
        items = []
        for key in keys[:50]:
            # Corruption is an explicit failure, never a successful empty list.
            item = self.describe(key, verify=False)
            items.append({k: item[k] for k in ('id', 'project', 'created_at')})
        self.check_scope()
        return {'items': items, 'next_cursor': keys[49] if len(keys) > 50 else None}

    def save(self, raw, expected, checker):
        self.check_scope()
        _hash(expected)
        report = checker(raw)
        if report.get('error'):
            raise CreatorContractError(report.get('code', 'invalid_source_package'))
        if (report.get('schema') != 'runteams.source-import-inspection/2-dev' or
                report.get('scope') != 'local-preflight' or report.get('imported') is not False or
                report.get('source', {}).get('sha256') != expected):
            raise CreatorContractError('source_changed_since_inspection')
        return self._persist(raw, expected, report)


    def _persist(self, raw, expected, report):
        self.check_scope()
        destination = self._directory(expected)
        if destination.exists():
            return self.describe(expected)
        value = {k: report[k] for k in ('project', 'source', 'employees', 'pipelines', 'dependencies')}
        value.update(schema=SCHEMA, id=expected, scope='device-source-draft',
                     published=False, cloud_verified=False,
                     created_at=datetime.now(timezone.utc).isoformat(),
                     archive_sha256=hashlib.sha256(raw).hexdigest())
        staging = Path(tempfile.mkdtemp(prefix='.import-', dir=self.root))
        try:
            for name, body in [('source.zip', raw), ('draft.json', canonical(value))]:
                fd = os.open(staging / name, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
                with os.fdopen(fd, 'wb') as stream:
                    stream.write(body); stream.flush(); os.fsync(stream.fileno())
            _sync(staging)
            self.check_scope()
            try:
                # Complete directory becomes visible atomically. A concurrent
                # import can win; its immutable receipt is the same draft.
                os.rename(staging, destination)
            except OSError as error:
                if error.errno not in (errno.EEXIST, errno.ENOTEMPTY):
                    raise
            _sync(self.root)
            return self.describe(expected)
        finally:
            if staging.exists():
                shutil.rmtree(staging)


def current_store(expected_scope):
    from . import device_data
    scope = device_data.identity()
    if expected_scope != scope['cache_scope']:
        raise PermissionError('账户已变化，请重新打开作品文件。')
    if scope.get('organization_id'):
        raise PermissionError('请切换到个人空间，再导入本机源码。')
    return LocalSources(device_data.root() / 'creator-sources', lambda: device_data.check(scope))


def snapshot(source, destination, _scope, check):
    source = Path(source) / 'creator-sources'
    if not source.exists() and not source.is_symlink():
        return
    store = LocalSources(source, check)
    # Capture complete immutable drafts only; an in-flight staging directory is
    # not a saved draft. No source can be edited underneath this snapshot.
    for key in sorted(p.name for p in source.iterdir() if HASH.fullmatch(p.name)):
        metadata = store.describe(key)
        raw = store.archive(key, metadata=metadata)
        target = Path(destination) / 'creator-sources' / key
        target.mkdir(mode=0o700, parents=True)
        for name, body in [('draft.json', canonical(metadata)), ('source.zip', raw)]:
            with (target / name).open('xb') as stream:
                stream.write(body); stream.flush(); os.fsync(stream.fileno())
            (target / name).chmod(0o600)
        from .creator_source_revisions import Revisions
        Revisions(store, key).snapshot(target)
        check()
