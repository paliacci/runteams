from runteams_core.foundation.resources import root as resource_root
"""Durable personal device data, deliberately separate from disposable caches.

Cloud owns business objects and permissions. This store owns personal chat
content and device interaction preferences; it is never a cloud failure fallback.
"""
from contextlib import contextmanager
from contextvars import ContextVar
import json
from pathlib import Path
import sqlite3
from runteams_core.conversations.page_paths import chat_key, short_ids
import stat
import secrets
import re
import uuid
import threading
from functools import lru_cache

from runteams_core.foundation.regular_files import sqlite_file_uri
from runteams_core.storage import local_database
from runteams_core.conversations.workspace_context import selected


_active = ContextVar('device_data_connection', default=None)
_schema_lock = threading.RLock()
SCHEMA_VERSION = 8
LOCAL_CHAT_ID_MIN = 2**48


def identity():
    return dict(_binding().scope)


def _binding():
    from runteams_core.storage.storage_context import resolve
    return resolve(Path(local_database.DB_PATH).resolve().parent / 'device-data')


def assets():
    from runteams_core.assets.library_assets import LocalAssets
    binding = _binding()
    scope = dict(binding.scope)
    return LocalAssets(binding.root, binding.library_id, lambda: check(scope))


def enabled():
    # Legacy domain fixtures explicitly choose their own complete adapter.
    from runteams_core.storage.business_storage import bound_storage
    return bound_storage(local_database.DB_PATH) is None


def personal():
    return enabled() and not selected()


def root():
    from runteams_core.storage.local_library import private_directory
    path = _binding().root
    for part in (path.parent, path):
        private_directory(part)
    return path


def check(expected):
    if identity() != expected:
        raise PermissionError('账户或工作区已变化，请重新打开。')


def _knowledge_schema(version):
    knowledge = (resource_root() / 'contracts/device-asset-knowledge.sql').read_text(encoding='utf-8')
    if version < 8:
        knowledge = knowledge.split('ALTER TABLE asset_sources', 1)[0]
    return knowledge if version >= 7 else knowledge.replace('pages >= 0', 'pages > 0')


@lru_cache(maxsize=8)
def schema(version=SCHEMA_VERSION):
    directory = resource_root() / 'contracts'
    statements = [(directory / name).read_text(encoding='utf-8') for name in ('device-user-data.sql', 'chat-tables.sql')]
    statements.append('CREATE INDEX device_messages_chat ON chat_messages(chat_id,id);')
    statements.extend((directory / name).read_text(encoding='utf-8') for name in (
        'device-creator-work.sql', 'device-runtime-links.sql'))
    statements.append((directory / 'device-collections.sql').read_text(encoding='utf-8'))
    if version >= 6:
        statements.append(_knowledge_schema(version))
    return '\n'.join(statements)


def _initialize(c):
    from runteams_core.storage.device_schema import execute, verify
    if c.execute('PRAGMA user_version').fetchone()[0] == SCHEMA_VERSION:
        verify(c, schema())
        return
    with _schema_lock:
        version = c.execute('PRAGMA user_version').fetchone()[0]
        if version == SCHEMA_VERSION:
            verify(c, schema())
            return
        if version not in (0, 5, 6, 7) or (version == 0 and c.execute(
                "SELECT 1 FROM sqlite_master WHERE name NOT LIKE 'sqlite_%' LIMIT 1").fetchone()):
            raise ValueError('本机数据版本不受支持，原资料保持不变。')
        c.execute('PRAGMA journal_mode=WAL')
        c.execute('BEGIN IMMEDIATE')
        try:
            # A competing initializer may have completed while this one waited.
            version = c.execute('PRAGMA user_version').fetchone()[0]
            if version == SCHEMA_VERSION:
                verify(c, schema())
            elif version in (5, 6, 7):
                _upgrade_knowledge(c, version)
                c.execute('PRAGMA user_version=' + str(SCHEMA_VERSION))
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


def _upgrade_knowledge(c, version):
    from runteams_core.storage.device_schema import execute, verify
    verify(c, schema(version))
    knowledge = _knowledge_schema(7)
    if version == 5:
        execute(c, knowledge)
    elif version == 6:
        c.execute('ALTER TABLE asset_source_pages RENAME TO old_source_pages')
        c.execute('ALTER TABLE asset_sources RENAME TO old_sources')
        execute(c, knowledge[knowledge.index('CREATE TABLE asset_sources'):])
        c.execute('INSERT INTO asset_sources SELECT * FROM old_sources')
        c.execute('INSERT INTO asset_source_pages SELECT * FROM old_source_pages')
        c.execute('DROP TABLE old_source_pages')
        c.execute('DROP TABLE old_sources')
    execute(c, _knowledge_schema(SCHEMA_VERSION)[len(knowledge):])


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
    c = sqlite3.connect(sqlite_file_uri(path), uri=True, timeout=30)
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
        from runteams_core.storage.storage_context import notify_saved
        notify_saved(scope)


def page_ids(public_chat=None):
    if not personal():
        raise PermissionError('请在个人工作区打开本机对话。')
    binding = _binding()
    scope = dict(binding.scope)
    key = None
    where = 'WHERE i.deleted=0'
    params = ()
    if public_chat is not None:
        from runteams_core.storage.page_id_store import lookup
        if not isinstance(public_chat, str) or not re.fullmatch(r'[0-9][a-z][a-z0-9]{6}', public_chat):
            raise ValueError('本机对话链接无效。')
        key = lookup(root(), public_chat)
        # The owning library can rebuild a missing index from its durable chat IDs.
        if key is not None:
            where += ' AND i.identity=?'
            params = (str(uuid.UUID(key[5:])) if re.fullmatch(r'chat:[a-f0-9]{32}', key) else '',)
    with connect(readonly=True) as c:
        rows = c.execute(
            'SELECT i.chat_id,i.identity,c.kind,c.context_json,'
            'EXISTS(SELECT 1 FROM chat_messages m WHERE m.chat_id=i.chat_id) AS has_messages '
            'FROM device_chat_index i JOIN chats c ON c.id=i.chat_id ' + where, params
        ).fetchall()
    from runteams_core.conversations.page_paths import chat_owner_paths
    ids = {key:public_chat} if key is not None else short_ids(chat_key(row['identity']) for row in rows)
    if public_chat is not None:
        rows = [row for row in rows if ids[chat_key(row['identity'])] == public_chat]
    contexts = [json.loads(row['context_json'] or '{}') for row in rows]
    items, layouts = [], {}
    for row, context, owner in zip(rows, contexts, chat_owner_paths(contexts), strict=True):
        public_id = ids[chat_key(row['identity'])]
        items.append({'resource':'chats','id':str(row['chat_id']),'public_id':public_id,
                      'owner_path':owner})
        if row['has_messages']:
            layouts[public_id] = 'history'
        elif row['kind'] == 'employee_design':
            layouts[public_id] = 'employee'
        elif row['kind'] == 'general':
            layouts[public_id] = ('pipeline' if context.get('source_pipeline_workspace') else
                                  'employee' if context.get('context_type') == 'worker' else
                                  'create-employee' if context.get('purpose') == 'create-employee' else 'general')
    check(scope)
    return {'version':1,'library_id':binding.library_id,
        **({'account_id':scope['account_id']} if 'account_id' in scope else {}),
        'items':items, 'conversation_layouts':layouts}


def employee_conversations(connection, employee_id=None):
    """Personal, directly assigned conversations, including empty ones."""
    query = (
        "SELECT c.id,c.employee_id,c.updated_at,c.context_json,i.identity,"
        "(SELECT m.id FROM chat_messages m WHERE m.chat_id=c.id ORDER BY m.id DESC LIMIT 1) AS last_message_id "
        "FROM chats c JOIN device_chat_index i ON i.chat_id=c.id "
        "WHERE i.deleted=0 AND c.kind='general' AND c.subject_type='employee' "
        "AND c.scope_type='global' AND c.employee_id IS NOT NULL"
    )
    if employee_id is not None:
        query += ' AND c.employee_id=?'
    rows = connection.execute(query + ' ORDER BY last_message_id IS NOT NULL DESC,c.updated_at DESC,c.id DESC',
                              () if employee_id is None else (employee_id,)).fetchall()
    ids = short_ids(chat_key(row['identity']) for row in rows)
    for row in rows:
        try:
            context = json.loads(row['context_json'] or '{}')
        except ValueError:
            continue
        if (not isinstance(context, dict) or context.get('context_type') != 'worker'
                or context.get('pipeline_work') or context.get('source_pipeline_workspace')):
            continue
        yield {'id': row['id'], 'employee_id': row['employee_id'], 'updated_at': row['updated_at'],
               'public_id': ids[chat_key(row['identity'])], 'last_message_id': row['last_message_id'],
               'employee_reference': context.get('employee_reference'), 'storage_scope': 'device'}


def public_id(chat_id):
    key = chat_key(epoch(chat_id))
    return short_ids([key])[key]


def eligible(record):
    context = record.get('context') or {}
    if isinstance(context, str):
        context = json.loads(context)
    if record.get('kind')=='employee_design':
        from runteams_core.authoring.creator_local_authoring import valid_context
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
        from runteams_core.configuration.interaction_settings import validate
        validate(value)
        c.execute("INSERT INTO device_settings(key,value) VALUES('interaction',?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (json.dumps(value, ensure_ascii=False, separators=(',',':')),))
    return value
