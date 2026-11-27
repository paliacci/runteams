"""Folders in the personal device library, keyed to stable document lineages."""
import json
import re
import sqlite3

from runteams_core.documents import rich_documents
from runteams_core.foundation.contracts import ContractError, digest
from runteams_core.work.device_work import DeviceWorkStorage

_UUID = r'[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}'
_MOVE_EVENT = 'document_folder.documents_moved'


def _require_device(core):
    if not isinstance(core.repository.storage, DeviceWorkStorage):
        raise PermissionError('请在个人工作区打开本机文档。')
    core._actor()


def _folder_id(value, *, root=False):
    if root and value == '':
        return None
    if not isinstance(value, str) or not re.fullmatch(_UUID, value):
        raise ContractError('文件夹标识无效。')
    return value


def _folder(connection, identifier):
    if identifier is None:
        return None
    folder = connection.execute(
        'SELECT id,parent_id,name FROM document_folders WHERE id=?', (identifier,)).fetchone()
    if folder is None:
        raise ContractError('文件夹已不存在，请返回文档根目录。')
    return folder


def page(core, folder, **options):
    _require_device(core)
    folder = '' if folder == 'root' else folder
    identifier = _folder_id(folder, root=True)
    with core.repository.read_snapshot() as connection:
        folders = [dict(row) for row in connection.execute(
            'SELECT id,parent_id,name FROM document_folders ORDER BY name COLLATE NOCASE,id')]
        if identifier and not any(row['id'] == identifier for row in folders):
            return {'documents': [], 'has_more': False, 'next_cursor': None,
                    'folders': folders, 'folder_missing': True}
        return {**core.document_page(folder_id=folder, **options), 'folders': folders}


def _place(connection, root, folder):
    if folder is None:
        connection.execute('DELETE FROM document_folder_entries WHERE document_id=?', (root,))
    else:
        connection.execute(
            'INSERT INTO document_folder_entries(document_id,folder_id) VALUES(?,?) '
            'ON CONFLICT(document_id) DO UPDATE SET folder_id=excluded.folder_id', (root, folder))


def create_document(core, folder, **options):
    _require_device(core)
    identifier = _folder_id(folder, root=True)
    if not isinstance(options['document_key'], str) or not options['document_key'].strip():
        raise ContractError('新建文档需要有效的文档标识。')
    with core.repository.definition_lock(), core.repository.connect() as connection:
        existing = core._find_agent_document(connection, options['document_key'])
        if existing is None:
            _folder(connection, identifier)
        result = rich_documents.write(core, **options)
        if existing is None and not result.get('conflict'):
            _place(connection, result['id'], identifier)
        return result


def mutate(core, data):
    _require_device(core)
    action = data.get('action')
    fields = {
        'create': {'folder', 'parent', 'name'},
        'rename': {'folder', 'name'},
        'delete': {'folder'},
        'move_document': {'document', 'folder'},
        'move_documents': {'documents', 'folder'},
    }
    if action == 'move_documents' and 'operation_id' in data:
        fields[action].add('operation_id')
    if not isinstance(action, str) or action not in fields or set(data) != fields[action] | {'action'}:
        raise ContractError('文件夹操作无效。')
    identifier = _folder_id(data['folder'], root=action in ('move_document', 'move_documents'))
    with core.repository.definition_lock(), core.repository.connect() as connection:
        if action == 'create':
            parent = _folder_id(data['parent'], root=True)
            _folder(connection, parent)
            _save_folder(connection, identifier, data['name'], parent=parent)
        elif action == 'rename':
            _folder(connection, identifier)
            _save_folder(connection, identifier, data['name'], rename=True)
        elif action == 'delete':
            if connection.execute('SELECT 1 FROM document_folders WHERE parent_id=? '
                                  'UNION ALL SELECT 1 FROM document_folder_entries WHERE folder_id=? LIMIT 1',
                                  (identifier, identifier)).fetchone():
                raise ContractError('请先移出此文件夹中的文档和子文件夹。')
            connection.execute('DELETE FROM document_folders WHERE id=?', (identifier,))
        else:
            documents = [data['document']] if action == 'move_document' else data['documents']
            if 'operation_id' in data and (not isinstance(data['operation_id'], str)
                                           or not re.fullmatch(_UUID, data['operation_id'])):
                raise ContractError('文档移动操作标识无效。')
            _move(core, connection, documents, identifier, data.get('operation_id'))
    return {'ok': True, 'storage_scope': 'device'}


def _move(core, connection, documents, folder, operation_id):
    if not isinstance(documents, list) or not documents or any(
            type(document) is not int or not 0 < document < 2**53 for document in documents):
        raise ContractError('请选择要移动的文档。')
    documents = sorted(set(documents))
    if operation_id:
        stream = 'document-folder-move:' + operation_id
        request_digest = digest({'folder': folder, 'documents': documents})
        prior = connection.execute('SELECT data_json FROM events WHERE stream=? AND type=?',
                                   (stream, _MOVE_EVENT)).fetchone()
        if prior:
            if json.loads(prior['data_json'])['request_digest'] != request_digest:
                raise ContractError('此移动操作已用于其他文档或目标文件夹。')
            return
    _folder(connection, folder)
    for document in documents:
        row = connection.execute('SELECT * FROM artifacts WHERE id=? AND trashed_at IS NULL',
                                 (document,)).fetchone()
        if row is None or not core.is_document_artifact(core._decode_meta(row['meta_json']), row['name']):
            raise ContractError('文档已不存在，请刷新文档列表。')
        _place(connection, core._document_root_id(row), folder)
    if operation_id:
        core.repository.event(stream, _MOVE_EVENT, {'request_digest': request_digest}, connection=connection)


def _save_folder(connection, identifier, name, *, parent=None, rename=False):
    name = name.strip() if isinstance(name, str) else ''
    if not 0 < len(name) <= 100 or re.search(r'[\x00-\x1f\x7f/\\]', name):
        raise ContractError('请输入有效的文件夹名称，最多 100 个字。')
    try:
        if rename:
            connection.execute('UPDATE document_folders SET name=? WHERE id=?', (name, identifier))
        else:
            connection.execute(
                'INSERT INTO document_folders(id,parent_id,name) VALUES(?,?,?) ON CONFLICT(id) DO NOTHING',
                (identifier, parent, name))
    except sqlite3.IntegrityError as error:
        if error.sqlite_errorname != 'SQLITE_CONSTRAINT_UNIQUE':
            raise
        raise ContractError('这个位置已有同名文件夹。') from None
