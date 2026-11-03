from runteams_core.resources import root as resource_root
"""Durable personal device data, deliberately separate from disposable caches.

Cloud owns business objects and permissions. This store owns personal chat
content and device interaction preferences; it is never a cloud failure fallback.
"""
from contextlib import contextmanager
from contextvars import ContextVar
import json
from pathlib import Path
import sqlite3
import stat
import secrets
import threading

from runteams_core import local_database
from .workspace_context import selected


_active = ContextVar('device_data_connection', default=None)
_schema_lock = threading.RLock()
SCHEMA_VERSION = 5
LOCAL_CHAT_ID_MIN = 2**48


def identity():
    return dict(_binding().scope)


def _binding():
    from .storage_context import resolve
    return resolve(Path(local_database.DB_PATH).resolve().parent / 'device-data')


def assets():
    from .library_assets import LocalAssets
    binding = _binding()
    scope = dict(binding.scope)
    return LocalAssets(binding.root, binding.library_id, lambda: check(scope))


def enabled():
    # Legacy domain fixtures explicitly choose their own complete adapter.
    from .business_storage import bound_storage
    return bound_storage(local_database.DB_PATH) is None


def personal():
    return enabled() and not selected()


def root():
    from .local_library import private_directory
    path = _binding().root
    for part in (path.parent, path):
        private_directory(part)
    return path


def check(expected):
    if identity() != expected:
        raise PermissionError('账户或工作区已变化，请重新打开。')


def schema():
    directory = resource_root() / 'contracts'
    business = (directory / 'cloud-business-transaction.sql').read_text()
    statements = [(directory / 'device-user-data.sql').read_text()]
    for table in ('chats', 'chat_messages'):
        start = business.index('CREATE TABLE ' + table + '(')
        statements.append(business[start:business.index(';', start)+1])
    statements.append('CREATE INDEX device_messages_chat ON chat_messages(chat_id,id);')
    statements.extend((directory / name).read_text() for name in (
        'device-creator-work.sql', 'device-runtime-links.sql'))
    statements.append((directory / 'device-collections.sql').read_text())
    return '\n'.join(statements)


def _initialize(c):
    from .device_schema import execute, verify
    with _schema_lock:
        version = c.execute('PRAGMA user_version').fetchone()[0]
        if version == SCHEMA_VERSION:
            verify(c, schema())
            return
        if version != 0 or c.execute(
                "SELECT 1 FROM sqlite_master WHERE name NOT LIKE 'sqlite_%' LIMIT 1").fetchone():
            raise ValueError('本机数据版本不受支持，原资料保持不变。')
        c.execute('PRAGMA journal_mode=WAL')
        c.execute('BEGIN IMMEDIATE')
        try:
            # A competing initializer may have completed while this one waited.
            version = c.execute('PRAGMA user_version').fetchone()[0]
            if version == SCHEMA_VERSION:
                verify(c, schema())
            elif version == 0 and not c.execute(
                    "SELECT 1 FROM sqlite_master WHERE name NOT LIKE 'sqlite_%' LIMIT 1").fetchone():
                execute(c, schema())
                c.execute("INSERT INTO sqlite_sequence(name,seq) VALUES('chat_messages',?)",
                          (2**42 + secrets.randbelow(2**40),))
                c.execute('PRAGMA user_version=' + str(SCHEMA_VERSION))
                verify(c, schema())
            else:
                raise ValueError('本机数据版本不受支持，原资料保持不变。')
            c.commit()
        except BaseException:
            c.rollback()
            raise


@contextmanager
def connect(*, readonly=False):
    scope = identity()
    path = root() / 'personal.sqlite3'
    if path.is_symlink():
        raise ValueError('本机数据文件无效。')
    active = _active.get()
    if active and active['path'] == path:
        check(active['scope'])
        try:
            if active['readonly'] and not readonly:
                raise ValueError('读取事务不能升级为写入。')
            yield active['connection']
            check(active['scope'])
        except BaseException:
            active['failed'] = True
            raise
        return
    c = sqlite3.connect(path, timeout=30)
    if stat.S_IMODE(path.stat().st_mode) != 0o600:
        path.chmod(0o600)
    c.row_factory = sqlite3.Row
    changed = False
    try:
        _initialize(c)
        c.execute('PRAGMA foreign_keys=ON')
        if readonly:
            c.execute('PRAGMA query_only=ON')
        c.execute('BEGIN' if readonly else 'BEGIN IMMEDIATE')
        check(scope)
        state = {'path': path, 'connection': c, 'scope': scope, 'failed': False, 'readonly':readonly}
        token = _active.set(state)
        try:
            yield c
            check(scope)
            if state['failed']:
                raise ValueError('本机保存未完成，请重新读取。')
            c.commit()
            changed = not readonly and c.total_changes > 0
        finally:
            _active.reset(token)
    except BaseException:
        c.rollback()
        raise
    finally:
        c.close()
    if changed:
        from .storage_context import notify_saved
        notify_saved(scope)


def page_ids():
    if not personal():
        raise PermissionError('请在个人工作区打开本机对话。')
    scope = identity()
    with connect(readonly=True) as c:
        rows = c.execute('SELECT chat_id,identity FROM device_chat_index WHERE deleted=0').fetchall()
    return {'version':1,'library_id':_binding().library_id,
        **({'account_id':scope['account_id']} if 'account_id' in scope else {}),'items':[
        {'resource':'chats','id':str(row['chat_id']),'public_id':'local-'+row['identity'].replace('-','')}
        for row in rows]}


def public_id(chat_id):
    return 'local-'+epoch(chat_id).replace('-','')


def eligible(record):
    context = record.get('context') or {}
    if isinstance(context, str):
        context = json.loads(context)
    if record.get('kind')=='employee_design':
        from .creator_local_authoring import valid_context
        return bool(valid_context(context) and not record.get('scope_pipeline_id') and not record.get('scope_run_id'))
    subject = record.get('subject_type', 'workspace')
    ordinary = subject == 'workspace' and context.get('context_type', 'general') == 'general'
    employee = (subject == 'employee' and context.get('context_type') == 'worker'
        and context.get('intent', 'chat') in ('chat', 'work'))
    return (record.get('kind', 'general') == 'general' and (ordinary or employee)
        and not record.get('scope_pipeline_id') and not record.get('scope_run_id')
        and record.get('scope_type', 'global') == 'global'
        and not context.get('creator_authoring'))


def contains(chat_id):
    if not personal():
        return False
    with connect(readonly=True) as c:
        return c.execute('SELECT 1 FROM device_chat_index WHERE chat_id=?', (int(chat_id),)).fetchone() is not None


def epoch(chat_id):
    with connect(readonly=True) as c:
        row = c.execute('SELECT identity FROM device_chat_index WHERE chat_id=?', (int(chat_id),)).fetchone()
        if not row:
            raise ValueError('本机对话不存在。')
        return row['identity']


def settings():
    with connect(readonly=True) as c:
        row = c.execute("SELECT value FROM device_settings WHERE key='interaction'").fetchone()
    return json.loads(row['value']) if row else {}


def update_settings(patch, *, replace=False):
    with connect() as c:
        row = c.execute("SELECT value FROM device_settings WHERE key='interaction'").fetchone()
        value = {} if replace or not row else json.loads(row['value'])
        value.update(patch)
        from .interaction_settings import validate
        validate(value)
        c.execute("INSERT INTO device_settings(key,value) VALUES('interaction',?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (json.dumps(value, ensure_ascii=False, separators=(',',':')),))
    return value
