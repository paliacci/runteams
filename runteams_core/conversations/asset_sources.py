"""Durable source snapshots for direct asset conversations."""
from contextlib import closing, contextmanager
from functools import cache
from pathlib import Path
import base64
import hashlib
import io
import json
import os
import tempfile
import secrets
import threading
import time
from runteams_core.assets import knowledge_archive
from runteams_core.documents import office_text

from runteams_core.storage import device_data

FORMATS = {'.md', '.markdown', '.txt', '.pdf', '.csv', '.json', '.srt', '.vtt'} | office_text.FORMATS
CATALOG_SIZE = 12
EXCERPT_SIZE = 4000


def _pages(name, raw):
    from runteams_core.conversations import chat_attachments as files
    suffix = Path(name).suffix.lower()
    if suffix in office_text.FORMATS:
        return office_text.pages(suffix, raw)
    if suffix != '.pdf':
        return [raw.decode('utf-8-sig').replace('\r\n', '\n').replace('\r', '\n')]
    import pypdfium2 as pdfium
    pages = []
    size = 0
    with files.PDF_LOCK, closing(pdfium.PdfDocument(raw)) as document:
        if len(document) > files.MAX_PDF_PAGES:
            raise ValueError(f'PDF 超过 {files.MAX_PDF_PAGES} 页，请拆分后上传。')
        for page in document:
            with closing(page), closing(page.get_textpage()) as text:
                value = text.get_text_bounded()
            size += len(value)
            if size > files.MAX_EXTRACTED_TEXT_CHARS:
                raise ValueError('PDF 文本过长，请拆分后上传。')
            pages.append(value)
    return pages


def readable_pages(name, raw):
    if Path(name).suffix.lower() not in FORMATS:
        return []
    try:
        pages = _pages(name, raw)
    except (ValueError, RuntimeError):
        return []
    return pages if any(page.strip() for page in pages) else []


def _store(connection, bank, name, raw, pages):
    source = connection.execute(
        'INSERT INTO asset_sources(id,bank,name,original,pages,revision) VALUES(?,?,?,?,?,lower(hex(randomblob(16)))) '
        'ON CONFLICT(bank,name) DO UPDATE SET original=excluded.original,pages=excluded.pages,revision=excluded.revision '
        'RETURNING id', (_new_id(), bank, name, raw, len(pages))).fetchone()[0]
    connection.execute('DELETE FROM asset_source_pages WHERE source_id=?', (source,))
    connection.executemany('INSERT INTO asset_source_pages(source_id,page,text) VALUES(?,?,?)',
                           ((source, i, page) for i, page in enumerate(pages, 1)))
    return source


def _new_id():
    # Keep identifiers distinct after deletion and exactly representable in browser clients.
    return (1 << 52) + secrets.randbits(52)


def _available_bundled(connection, bank, bundled):
    if not bundled:
        return {}
    excluded = {r[0] for r in connection.execute('SELECT source FROM asset_bundled_exclusions WHERE bank=?', (bank,))}
    return {key: row for key, row in bundled.items() if key not in excluded}


def _bundled_record(bank, source, bundled):
    if source not in (bundled or {}):
        raise ValueError('资料不属于当前资产版本。')
    with device_data.connect(readonly=True) as c:
        row = _available_bundled(c, bank, {source: bundled[source]}).get(source)
    if row is None:
        raise ValueError('资料已从当前资产知识库移除。')
    return row


def _prior_source(connection, bank, source, revision, bundled):
    if isinstance(source, str):
        row = _available_bundled(connection, bank, bundled).get(source)
        if row is None:
            raise ValueError('随包资料已变化，请重新读取资料目录。')
        return {'id': source, 'name': row['path'], 'origin': 'bundled'}
    row = connection.execute(
        'SELECT id,name FROM asset_sources WHERE bank=? AND id=? AND revision=?',
        (bank, source, revision)).fetchone()
    if row is None:
        raise ValueError('个人资料已变化，请重新读取资料目录。')
    return {**dict(row), 'origin': 'personal'}


def apply_chat_change(connection, bank, operation, action, staged, *, source=None, revision=None, bundled=None):
    prior = _prior_source(connection, bank, source, revision, bundled) if source is not None else None
    names = [name for name, _, _ in staged]
    if len(set(names)) != len(names):
        raise ValueError('所选附件中有同名文件，请先明确需要加入的版本。')
    for name in names:
        row = connection.execute('SELECT id FROM asset_sources WHERE bank=? AND name=?', (bank, name)).fetchone()
        if row is not None and (prior is None or row['id'] != prior['id']):
            raise ValueError(f'已有同名个人资料「{name}」，请明确要替换的资料。')

    if prior and prior['origin'] == 'bundled':
        connection.execute('INSERT INTO asset_bundled_exclusions(bank,source) VALUES(?,?)', (bank, source))
    elif prior:
        connection.execute('DELETE FROM asset_sources WHERE bank=? AND id=?', (bank, source))

    added = [{'id': _store(connection, bank, name, raw, pages), 'name': name, 'pages': len(pages)}
             for name, raw, pages in staged]
    result = {'action': action, 'added': added, 'removed': prior}
    connection.execute('INSERT INTO asset_source_actions(operation,result) VALUES(?,?)',
                       (operation, json.dumps(result, ensure_ascii=False)))
    return result


UPLOAD_CHUNK = 2 * 1024 * 1024
_uploads = {}
_upload_lock = threading.Lock()


def _save_upload(bank, name, stream, size, replace):
    with device_data.connect() as c:
        if not replace and c.execute('SELECT 1 FROM asset_sources WHERE bank=? AND name=?', (bank,name)).fetchone():
            return {'duplicate': True}
        source = c.execute(
            'INSERT INTO asset_sources(id,bank,name,original,pages,revision) '
            'VALUES(?,?,?,zeroblob(?),0,lower(hex(randomblob(16)))) '
            'ON CONFLICT(bank,name) DO UPDATE SET original=excluded.original,pages=0,revision=excluded.revision RETURNING id',
            (_new_id(), bank, name, size)).fetchone()[0]
        stream.seek(0)
        with c.blobopen('asset_sources', 'original', source) as blob:
            knowledge_archive.copy_checked(stream, blob, size)
        c.execute('DELETE FROM asset_source_pages WHERE source_id=?', (source,))
        stream.seek(0)
        suffix = Path(name).suffix.lower()
        if suffix not in FORMATS:
            return {'saved': True}
        reader = None
        if suffix == '.pdf' or suffix in office_text.FORMATS:
            pages = readable_pages(name, stream)
        else:
            reader = io.TextIOWrapper(stream, encoding='utf-8-sig', newline=None)
            pages = iter(lambda: reader.read(256 * 1024), '')
        count = 0
        try:
            for count, page in enumerate(pages, 1):
                c.execute('INSERT INTO asset_source_pages(source_id,page,text) VALUES(?,?,?)', (source,count,page))
        except UnicodeDecodeError:
            c.execute('DELETE FROM asset_source_pages WHERE source_id=?', (source,))
            count = 0
        finally:
            if reader is not None:
                reader.detach()
        c.execute('UPDATE asset_sources SET pages=? WHERE id=?', (count,source))
    return {'saved': True}


def _upload(bank, args):
    # Handles are scoped to the current bank. Temporary files disappear on close or process exit.
    now = time.monotonic()
    with _upload_lock:
        for token in list(_uploads):
            if now - _uploads[token]['touched'] > 1800:
                _uploads.pop(token)['file'].close()
        if set(args) == {'upload', 'name', 'size'} and args['upload'] == 'begin':
            name, size = args['name'], args['size']
            if not isinstance(name, str) or Path(name).name != name or len(name) > 255 or type(size) is not int or size < 0:
                raise ValueError('知识库文件信息无效。')
            knowledge_archive.file_name(name)
            token = secrets.token_hex(24)
            _uploads[token] = dict(bank=bank, name=name, size=size, file=tempfile.TemporaryFile(), touched=now)
            return {'upload': token}
        token = args['upload']
        entry = _uploads.get(token) if isinstance(token, str) else None
        if not entry or entry['bank'] != bank:
            raise ValueError('本次导入已失效，请重新选择文件。')
        entry['touched'] = now
        stream = entry['file']
        if set(args) == {'upload', 'cancel'} and args['cancel'] is True:
            _uploads.pop(token)['file'].close()
            return {'cancelled': True}
        end = stream.seek(0, os.SEEK_END)
        if set(args) == {'upload', 'offset', 'chunk'}:
            offset, encoded = args['offset'], args['chunk']
            if type(offset) is not int or not 0 <= offset <= end or not isinstance(encoded,str) or len(encoded)>4*((UPLOAD_CHUNK+2)//3):
                raise ValueError('文件分段无效。')
            raw = base64.b64decode(encoded, validate=True)
            if not 0 < len(raw) <= UPLOAD_CHUNK or offset+len(raw) > entry['size']:
                raise ValueError('文件分段大小无效。')
            if offset == end:
                stream.write(raw)
            else:
                stream.seek(offset)
                if stream.read(len(raw)) != raw:
                    raise ValueError('文件分段与之前收到的内容不同。')
            return {'offset': offset+len(raw)}
        if set(args) != {'upload', 'replace'} or type(args['replace']) is not bool or end != entry['size']:
            raise ValueError('文件尚未完整接收。')
        # Claim this handle before committing so a concurrent request cannot modify its contents.
        _uploads.pop(token)
    try:
        result = _save_upload(bank, entry['name'], stream, end, args['replace'])
        if result.get('duplicate'):
            with _upload_lock:
                entry['touched'] = time.monotonic()
                _uploads[token] = entry
            return result
    except BaseException:
        stream.close()
        raise
    stream.close()
    return result


def catalog(bank, offset=0, *, bundled=None, limit=CATALOG_SIZE, include_personal=True):
    with device_data.connect(readonly=True) as c:
        bundled = _available_bundled(c, bank, bundled)
        count = 0
        rows = []
        if include_personal:
            count = c.execute('SELECT count(*) FROM asset_sources WHERE bank=?', (bank,)).fetchone()[0]
            rows = c.execute(
                "SELECT s.id,s.name,s.pages,s.revision,substr(p.text,1,160) AS preview,'personal' AS origin FROM asset_sources s "
                'LEFT JOIN asset_source_pages p ON p.source_id=s.id AND p.page=1 WHERE s.bank=? '
                'ORDER BY s.name,s.id LIMIT ? OFFSET ?', (bank, -1 if limit is None else limit, offset)).fetchall()
        if limit is None:
            limit = count + len(bundled)
    items = [dict(r) for r in rows]
    start = max(0, offset-count)
    keys = sorted(bundled, key=lambda k: (bundled[k]['path'], k))
    for key in keys[start:start+limit-len(items)]:
        r = bundled[key]
        items.append({'id':key,'name':r['path'],'size':r['size'],'origin':'bundled',
                      'employee_name':r.get('employee_name')})
    total = count + len(keys)
    return {'sources':items, 'total':total, 'next_offset':offset+limit if offset+limit<total else None}


def excerpt(bank, source, page, offset, *, bundled=None):
    if isinstance(source, str):
        row = _bundled_record(bank, source, bundled)
        name = row['path']
        pages = []
        from runteams_core.conversations.chat_attachments import MAX_FILE_BYTES
        if Path(name).suffix.lower() in FORMATS and row['size'] <= MAX_FILE_BYTES:
            import io
            out = io.BytesIO()
            with knowledge_archive.regular(row['file']) as f:
                knowledge_archive.copy_checked(f, out, row['size'], row['sha256'])
            pages = readable_pages(name, out.getvalue())
        if not pages:
            return {'name':name,'size':row['size'],'pages':0}
        if not 1 <= page <= len(pages) or offset > len(pages[page-1]):
            raise ValueError('原文位置无效。')
        text = pages[page-1]
        return {'name':name,'revision':row['sha256'],'pages':len(pages),'page':page,'offset':offset,'length':len(text),
                'text':text[offset:offset+EXCERPT_SIZE],
                'next_offset':offset+EXCERPT_SIZE if offset+EXCERPT_SIZE<len(text) else None}
    with device_data.connect(readonly=True) as c:
        row = c.execute(
            'SELECT s.name,s.revision,s.pages,p.page,substr(p.text,?,?) AS text,length(p.text) AS length '
            'FROM asset_sources s LEFT JOIN asset_source_pages p ON p.source_id=s.id AND p.page=? '
            'WHERE s.bank=? AND s.id=?',
            (offset + 1, EXCERPT_SIZE, page, bank, source)).fetchone()
    if row and row['pages']==0:
        return {'name':row['name'],'pages':0}
    if row is None or row['page'] is None or offset > row['length']:
        raise ValueError('资料或指定位置不存在，请重新读取资料目录。')
    return {**dict(row), 'offset': offset,
            'next_offset': offset + EXCERPT_SIZE if offset + EXCERPT_SIZE < row['length'] else None}


@contextmanager
def _original_source(bank, source, bundled):
    record = _bundled_record(bank, source, bundled) if isinstance(source, str) else None
    if record:
        name, size, sha = record['path'], record['size'], record['sha256']
        reader = knowledge_archive.regular(record['file'])
    else:
        with device_data.connect(readonly=True) as c:
            row = c.execute('SELECT name,length(original),revision FROM asset_sources WHERE bank=? AND id=?',(bank,source)).fetchone()
            if not row:
                raise ValueError('资料不存在。')
            name, size, revision = row
            with c.blobopen('asset_sources', 'original', source, readonly=True) as blob:
                sha = knowledge_archive.copy_checked(blob, None, size)
                blob.seek(0)
                yield name, size, sha, revision, blob
            return
    with reader as src:
        yield name, size, sha, sha, src


def original(bank, source, bundled, directory, *, for_work=False):
    """Write one authorized, verified original without following links or replacing existing work."""
    with _original_source(bank, source, bundled) as (name, size, sha, revision, src):
        result = _write_original(src, name, size, sha, directory, for_work)
        return {**result, 'revision': revision}


def _write_original(src, name, size, sha, directory, for_work=False):
    directory = Path(directory)
    if directory.is_symlink() or not directory.is_dir():
        raise ValueError('资料输出目录无效。')
    if for_work:
        for component in ('.runteams', 'knowledge', sha):
            directory = directory / component
            if directory.is_symlink():
                raise ValueError('知识库工作目录无效。')
            directory.mkdir(mode=0o700, exist_ok=True)
    target = directory / Path(name).name
    if target.exists():
        with knowledge_archive.regular(target) as existing:
            knowledge_archive.copy_checked(existing, None, size, sha)
    else:
        with tempfile.NamedTemporaryFile(dir=directory) as temp:
            knowledge_archive.copy_checked(src, temp, size, sha)
            temp.flush()
            try:
                os.link(temp.name, target)
            except FileExistsError:
                with knowledge_archive.regular(target) as existing:
                    knowledge_archive.copy_checked(existing, None, size, sha)
    return {'name':name,'path':str(target),'size':size}


@cache
def _viewer_directory():
    return tempfile.TemporaryDirectory(prefix='runteams-knowledge-')


def open_original(bank, source, bundled):
    """Preview readable content in the drawer's overlay, or open the verified file locally."""
    from runteams_core.conversations.chat_attachments import MAX_FILE_BYTES
    from runteams_core.foundation import file_manager

    image_types = {'.png':'image/png', '.jpg':'image/jpeg', '.jpeg':'image/jpeg',
                   '.webp':'image/webp', '.gif':'image/gif'}
    with _original_source(bank, source, bundled) as (name, size, sha, _, stream):
        knowledge_archive.file_name(name)
        suffix = Path(name).suffix.lower()
        if size <= MAX_FILE_BYTES and suffix in (image_types.keys() | (FORMATS - {'.pdf'})):
            output = io.BytesIO()
            knowledge_archive.copy_checked(stream, output, size, sha)
            if suffix in office_text.FORMATS:
                output.seek(0)
                return office_text.preview(suffix, output)
            if suffix in image_types:
                data = base64.b64encode(output.getvalue()).decode('ascii')
                return {'kind':'image', 'url':'data:' + image_types[suffix] + ';base64,' + data}
            return {'kind':'text', 'text':output.getvalue().decode('utf-8-sig', errors='replace')}

        # External readers need a stable copy after the request returns.
        directory = Path(_viewer_directory().name) / sha
        directory.mkdir(mode=0o700, exist_ok=True)
        path = _write_original(stream, name, size, sha, directory)['path']
    os.chmod(path, 0o400)
    file_manager.open_path(path)
    return {'kind':'opened'}


def drawer(data):
    """Resolve the displayed asset on the server before reading or adding sources."""
    from runteams_core.conversations import asset_memory, chat_attachments
    from runteams_core.employees import employee_binding
    from runteams_core.pipelines import pipeline_context, pipeline_references
    from runteams_core.storage import product_store
    if not device_data.personal():
        raise PermissionError('请在个人工作区打开资产知识库。')
    from runteams_core.assets.bundled_knowledge import catalog as bundled_catalog
    args = dict(data)
    cid = None
    if 'chat' in args:
        cid = args.pop('chat')
        if type(cid) is not int or cid <= 0 or not product_store.device_chat(cid):
            raise PermissionError('员工对话不属于当前资料库。')
        session = product_store.get_chat(cid, include_messages=False)
        if session and session['kind'] == 'employee_design':
            ref = employee_binding.authoring_reference(session)
        else:
            bound = asset_memory._binding(cid)
            if not bound or not bound['writable'] or session['subject_type'] != 'employee':
                raise PermissionError('请在员工的直属对话中打开知识库。')
            ref = bound['reference']
    else:
        ref = pipeline_references.checked_reference(args.pop('reference', None))
        pipeline_context.current().definition(ref)
    bank = asset_memory.bank_for(ref)
    if 'upload' in args:
        return _upload(bank, args)
    if set(args) == {'expanded'} and args['expanded'] is True:
        return catalog(bank, bundled=bundled_catalog(ref, cid), limit=None)
    if not args or set(args) == {'offset'}:
        offset = args.get('offset', 0)
        if type(offset) is not int or not 0 <= offset < 2**31:
            raise ValueError('资料列表位置无效。')
        result = catalog(bank, offset, bundled=bundled_catalog(ref, cid))
        result['previous_offset'] = max(0, offset-CATALOG_SIZE) if offset else None
        return result
    if 'source' in args:
        from runteams_core.authoring.source.creator_local_source import HASH
        sid = args['source']
        if not (type(sid) is int and 0 < sid < 2**53 or isinstance(sid,str) and HASH.fullmatch(sid)):
            raise ValueError('资料编号无效。')
    if set(args) == {'source', 'open'} and args['open'] is True:
        return open_original(bank, args['source'], bundled_catalog(ref, cid))
    if set(args) == {'source', 'export'} and args['export'] is True:
        directory = chat_attachments.choose_location('folder', '选择保存原文件的位置')
        if not directory:
            return {'cancelled':True}
        original(bank, args['source'], bundled_catalog(ref, cid), directory)
        return {'saved':True}
    if set(args) == {'source', 'page', 'offset'}:
        if not all(type(v) is int and 0 <= v < 2**53 for v in (args['page'], args['offset'])):
            raise ValueError('原文位置无效。')
        return excerpt(bank, args['source'], args['page'], args['offset'], bundled=bundled_catalog(ref, cid))
    if set(args) == {'name', 'data', 'replace'}:
        name, encoded = args['name'], args['data']
        if (not isinstance(name, str) or not name or len(name)>255 or Path(name).name!=name
                or Path(name).suffix.lower() not in knowledge_archive.TYPES or type(args['replace']) is not bool):
            raise ValueError('请选择支持的文档、图片、字幕或影音文件。')
        knowledge_archive.file_name(name)
        if not isinstance(encoded, str):
            raise ValueError('附件内容无效。')
        raw = chat_attachments._decode({'data': encoded})
        return _save_upload(bank, name, io.BytesIO(raw), len(raw), args['replace'])
    raise ValueError('知识库操作无效。')
