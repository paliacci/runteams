"""Portable Markdown for a saved work result, with its referenced media if any."""
import base64
from io import BytesIO
import json
from pathlib import Path
import re
from urllib.parse import quote
from zipfile import ZipFile, ZIP_DEFLATED

from runteams_core.documents import rich_document_assets, rich_documents
from runteams_core.documents.document_export import MAX_EXPORT_BYTES
from runteams_core.foundation.contracts import ContractError


def _filename(name):
    return re.sub(r'[\x00-\x1f\x7f/\\:]', '_', str(name)).strip(' .')[:160] or 'document'


def _inline(value):
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        return ''.join(map(_inline, value))
    if not isinstance(value, dict):
        return ''
    if value.get('type') == 'blockReference':
        return _reference(value['props'])
    text = value.get('text', '') or _inline(value.get('content', []))
    if value.get('styles', {}).get('code'):
        text = '`' + text + '`'
    if value.get('href'):
        return f"[{text}](<{value['href']}>)"
    return text


def _reference(props):
    return f"[{props.get('label') or props['blockId']}](runteams://document/{props['documentId']}#{props['blockId']})"


def _fenced(text, language):
    longest = max((len(run) for run in re.findall(r'`+', text)), default=0)
    fence = '`' * max(3, longest + 1)
    return f'{fence}{language}\n{text}\n{fence}'


def _table(rows):
    if not rows or not rows[0]:
        return ''
    width = max(map(len, rows))
    def line(row):
        cells = [str(cell).replace('|', r'\|').replace('\n', '<br>') for cell in row]
        return '| ' + ' | '.join(cells + [''] * (width - len(cells))) + ' |'
    return '\n'.join([line(rows[0]), line(['---'] * width), *(line(row) for row in rows[1:])])


def _block(block, sources, attachments):
    kind = block['type']
    props = block.get('props', {})
    content = block.get('content', [])
    if kind == 'markdown':
        return props['text']
    if kind in ('image', 'video', 'file'):
        asset = props.get('assetId')
        if not asset:
            return props.get('name', '')
        name = props.get('name') or asset
        target = attachments.setdefault(asset, f'assets/{asset}/{_filename(name)}')
        return f"{'!' if kind == 'image' else ''}[{name}]({quote(target)})"
    if kind == 'reference':
        return _reference(props)
    if kind == 'math':
        return '$$\n' + props.get('formula', '') + '\n$$'
    if kind == 'metric':
        return props.get('label', '') + ' ' + props.get('value', '')
    if kind in {'barChart', 'jsonData', 'dataTable'}:
        data = json.loads(props['data']) if props.get('data') else sources[props['source']]['data']
        if kind in {'dataTable', 'barChart'} and props.get('data') and not data.get('invalidCells'):
            columns = data['columns']
            rows = [[column['name'] for column in columns]]
            rows.extend([row.get(column['id'], '') for column in columns] for row in data['rows'])
            display = _table(rows)
        else:
            display = _fenced(json.dumps(data, ensure_ascii=False, indent=2), 'json')
        return props.get('title', '') + '\n\n' + display
    if kind == 'table' and isinstance(content, dict):
        return _table([[_inline(cell) for cell in row.get('cells', [])] for row in content.get('rows', [])])
    text = _inline(content)
    if kind == 'codeBlock':
        return _fenced(text, props.get('language', ''))
    if kind == 'heading':
        level = str(props.get('level', 1))
        return '#' * (int(level) if level in ('1', '2', '3', '4', '5', '6') else 1) + ' ' + text
    if kind == 'checkListItem':
        return ('- [x] ' if props.get('checked') else '- [ ] ') + text
    if kind == 'quote':
        return '\n'.join('> ' + line for line in text.splitlines())
    if kind == 'divider':
        return '---'
    return {'bulletListItem': '- ', 'numberedListItem': '1. '}.get(kind, '') + text


def export_handoff(core, detail):
    name = _filename(detail['name'])
    md_name = name if name.lower().endswith('.md') else name + '.md'
    assets = {}
    if detail.get('content_model') == rich_documents.MODEL:
        doc = rich_documents.validate(detail['content'])
        def parts(blocks):
            for block in blocks:
                yield _block(block, doc['sources'], assets)
                yield from parts(block.get('children', []))
        text = '\n\n'.join(part for part in parts(doc['blocks']) if part)
    else:
        text = detail['content']
    body = text.encode('utf-8')
    if not assets:
        return body, md_name, 'text/markdown; charset=utf-8'
    buffer = BytesIO()
    size = len(body)
    with ZipFile(buffer, 'w', ZIP_DEFLATED) as archive:
        archive.writestr(md_name, body)
        for identifier, target in assets.items():
            file = rich_document_assets.read(core, detail['id'], identifier)
            raw = base64.b64decode(file['data'].split(',', 1)[1], validate=True)
            size += len(raw)
            if size > MAX_EXPORT_BYTES:
                raise ContractError('导出内容过大，请单独下载附件。')
            archive.writestr(target, raw)
    return buffer.getvalue(), Path(md_name).stem + '.zip', 'application/zip'
