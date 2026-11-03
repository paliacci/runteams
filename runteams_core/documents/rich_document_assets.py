"""Account-scoped immutable document attachments and reusable block templates.

Files live in the existing work-store tree and its verified backup. No browser
database, native document kernel or separate identity/permission store is used.
"""
import base64
import hashlib
import json
import os
from pathlib import Path
import re
import tempfile

from runteams_core.foundation.contracts import ContractError

MAX_FILE = 20 * 1024 * 1024
MAX_ENCODED = 32 * 1024 * 1024
IDENTIFIER = re.compile(r'[a-f0-9]{64}')


def _document(core, identifier, write=False):
    core._actor()
    with core.repository.connect() as connection:
        row = connection.execute('SELECT * FROM artifacts WHERE id=? AND trashed_at IS NULL',
                                 (int(identifier),)).fetchone()
        if row is None or core._decode_meta(row['meta_json']).get('content_model') != 'rich-document':
            raise ContractError('请选择可用的新版文档。')
        root = core._document_root_id(row)
    detail = core.document_detail(identifier, include_content=False)
    if not detail or write and (not detail.get('editable') or detail.get('is_current_revision') is False):
        raise ContractError('这份文档当前不能编辑。')
    return root


def _directory(core, name, create=False):
    root = Path(core.root) / 'artifacts' / name
    if root.parent.is_symlink() or root.is_symlink():
        raise ContractError('文档资料目录无效。')
    if create:
        root.mkdir(mode=0o700, parents=True, exist_ok=True)
    return root


def _read(path, limit=MAX_ENCODED):
    if path.is_symlink() or not path.is_file() or path.stat().st_size > limit:
        raise ContractError('文档资料不可用。')
    try:
        return json.loads(path.read_text())
    except (ValueError, UnicodeError) as exc:
        raise ContractError('文档资料格式无效。') from exc


def _atomic(path, raw):
    fd, temporary = tempfile.mkstemp(prefix='.pending-', dir=path.parent)
    try:
        with os.fdopen(fd, 'wb') as handle:
            handle.write(raw)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def _encoded(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'),
                      allow_nan=False).encode()


def _file(value):
    if not isinstance(value, dict) or set(value) != {'name', 'type', 'data'}:
        raise ContractError('附件内容不完整。')
    name, mime, data = value['name'], value['type'], value['data']
    if (not isinstance(name, str) or not 0 < len(name) <= 240 or '\x00' in name
            or not isinstance(mime, str) or not re.fullmatch(r'[a-zA-Z0-9.+-]+/[a-zA-Z0-9.+-]+', mime)
            or not isinstance(data, str) or len(data) > 29 * 1024 * 1024):
        raise ContractError('附件信息无效。')
    match = re.fullmatch(r'data:[^;,]*;base64,([A-Za-z0-9+/=\r\n]+)', data)
    if not match:
        raise ContractError('附件格式无效。')
    try:
        raw = base64.b64decode(match[1].replace('\n', '').replace('\r', ''), validate=True)
    except ValueError as exc:
        raise ContractError('附件内容不完整。') from exc
    if not 0 < len(raw) <= MAX_FILE:
        raise ContractError('请选择不超过20 MB的非空文件。')
    return {'name': name, 'type': mime,
            'data': 'data:' + mime + ';base64,' + base64.b64encode(raw).decode()}


def upload(core, document_id, value):
    with core.repository.definition_lock():
        root = _document(core, document_id, write=True)
        file = _file(value)
        raw = _encoded({'schema': 'runteams.document-attachment/1', 'document_root': root, **file})
        identifier = hashlib.sha256(raw).hexdigest()
        path = _directory(core, 'rich-assets', create=True) / (identifier + '.json')
        if path.exists() or path.is_symlink():
            if path.is_symlink() or path.read_bytes() != raw:
                raise ContractError('已有附件校验失败，未覆盖原件。')
        else:
            _atomic(path, raw)
        core._actor()
        return {'id': identifier, 'name': file['name'], 'type': file['type']}


def read(core, document_id, identifier):
    with core.repository.definition_lock():
        root = _document(core, document_id)
        if not isinstance(identifier, str) or not IDENTIFIER.fullmatch(identifier):
            raise ContractError('附件标识无效。')
        path = _directory(core, 'rich-assets') / (identifier + '.json')
        value = _read(path)
        if hashlib.sha256(_encoded(value)).hexdigest() != identifier or value.get('document_root') != root:
            raise ContractError('附件不属于这份文档。')
        file = _file({key: value[key] for key in ('name', 'type', 'data')})
        core._actor()
        return {'id': identifier, **file}


def references(core, document, document_id):
    identifiers = set()
    def visit(blocks):
        for block in blocks:
            if block.get('type') in {'image', 'video', 'file'} and block.get('props', {}).get('assetId'):
                identifiers.add(block['props']['assetId'])
            visit(block.get('children', []))
    visit(document['blocks'])
    if identifiers and not document_id:
        raise ContractError('请先创建文档，再添加附件。')
    refs = []
    for identifier in identifiers:
        read(core, document_id, identifier)
        refs.append(str(_directory(core, 'rich-assets') / (identifier + '.json')))
    return sorted(refs)


def _templates(core, create=False):
    core._actor()
    directory = _directory(core, 'rich-templates', create=create)
    path = directory / 'index.json'
    items = _read(path, 1024 * 1024) if path.exists() or path.is_symlink() else []
    if (not isinstance(items, list) or len(items) > 100 or
            any(not isinstance(item, dict) or set(item) != {'id', 'name'} or
                not IDENTIFIER.fullmatch(str(item['id'])) or not isinstance(item['name'], str)
                for item in items)):
        raise ContractError('模板目录无法读取，原资料仍保留。')
    return directory, items


def templates(core, document_id):
    with core.repository.definition_lock():
        _document(core, document_id)
        return _templates(core)[1]


def template(core, document_id, identifier):
    with core.repository.definition_lock():
        _document(core, document_id)
        directory, items = _templates(core)
        if not any(item['id'] == identifier for item in items):
            raise ContractError('模板不存在。')
        return _read(directory / (identifier + '.json'))


def save_template(core, document_id, name, fragment):
    with core.repository.definition_lock():
        _document(core, document_id, write=True)
        if not isinstance(name, str) or not 0 < len(name.strip()) <= 100:
            raise ContractError('请填写模板名称，最多100个字。')
        if (not isinstance(fragment, dict) or fragment.get('schema') != 'runteams.block-fragment/1'
                or not isinstance(fragment.get('assets'), dict)):
            raise ContractError('模板内容不完整。')
        raw = _encoded(fragment)
        if len(raw) > MAX_ENCODED:
            raise ContractError('模板内容过大，请拆分后保存。')
        from runteams_core.documents.rich_documents import validate
        validate({'schema': 'runteams.rich-document/1', 'blocks': fragment.get('blocks'),
                  'sources': fragment.get('sources')})
        for asset in fragment['assets'].values():
            _file(asset)
        def validate_assets(blocks):
            for block in blocks:
                asset = block.get('props', {}).get('assetId')
                if asset and asset not in fragment['assets']:
                    raise ContractError('模板缺少附件。')
                validate_assets(block.get('children', []))
        validate_assets(fragment['blocks'])
        directory, items = _templates(core, create=True)
        if len(items) >= 100 or any(item['name'] == name.strip() for item in items):
            raise ContractError('已有同名模板或模板数量已达上限。')
        identifier = hashlib.sha256(raw + name.strip().encode()).hexdigest()
        _atomic(directory / (identifier + '.json'), raw)
        _atomic(directory / 'index.json', _encoded([*items, {'id': identifier, 'name': name.strip()}]))
        core._actor()
        return {'id': identifier, 'name': name.strip()}
