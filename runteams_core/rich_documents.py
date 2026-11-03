"""Rich bodies use the existing artifact identity, revisions and access boundary.

Snapshots are document-owned JSON, never queries, file paths or executable views.
New documents share one structured content model.
"""
import copy
import hashlib
import json
import uuid
import re
from pathlib import Path

from .contracts import ContractError
from .repository import utc_now

MODEL = 'rich-document'
SCHEMA = 'runteams.rich-document/1'
TEXT_TYPES = {'paragraph', 'heading', 'bulletListItem', 'numberedListItem',
              'checkListItem', 'toggleListItem', 'quote', 'codeBlock', 'table', 'divider'}
WIDGET_TYPES = {'markdown', 'dataTable', 'barChart', 'jsonData', 'metric'}
EXTENDED_TYPES = {'callout', 'reference', 'math', 'image', 'video', 'file', 'columns', 'column'}


def from_markdown(text):
    return {'schema': SCHEMA, 'blocks': [{'id': uuid.uuid4().hex, 'type': 'markdown',
            'props': {'text': text}, 'children': []}], 'sources': {}}


def validate(value):
    if isinstance(value, str):
        try: value = json.loads(value)
        except (ValueError, RecursionError) as exc: raise ContractError('文档内容格式无效。') from exc
    if not isinstance(value, dict) or set(value) != {'schema', 'blocks', 'sources'} or value['schema'] != SCHEMA:
        raise ContractError('文档内容格式无效。')
    try: encoded = json.dumps(value, ensure_ascii=False, allow_nan=False)
    except (ValueError, TypeError, RecursionError) as exc: raise ContractError('文档数据无效。') from exc
    if len(encoded.encode()) > 2 * 1024 * 1024: raise ContractError('文档内容超过2 MB。')
    sources = value['sources']
    if not isinstance(sources, dict) or len(sources) > 30: raise ContractError('文档数据快照无效。')
    for key, source in sources.items():
        if not isinstance(key, str) or not isinstance(source, dict) or set(source) != {'label', 'data'} or not isinstance(source['label'], str):
            raise ContractError('文档数据快照无效。')
    seen = set()
    def reference(props):
        if (not isinstance(props,dict) or set(props)-{'documentId','blockId','label'} or
                not re.fullmatch(r'[1-9][0-9]{0,15}',str(props.get('documentId',''))) or
                not re.fullmatch(r'[a-zA-Z0-9._:-]{1,128}',str(props.get('blockId',''))) or
                not isinstance(props.get('label',''),str) or len(props.get('label',''))>500):
            raise ContractError('文档引用无效。')
    def data_model(raw):
        try:
            model=json.loads(raw)
            json.dumps(model,allow_nan=False)
        except (ValueError,TypeError) as exc:raise ContractError('编辑数据格式无效。') from exc
        if (not isinstance(model,dict) or set(model)-{'columns','rows','invalidCells'} or
                not isinstance(model.get('columns'),list) or not 1<=len(model['columns'])<=100 or
                not isinstance(model.get('rows'),list) or len(model['rows'])>5000):
            raise ContractError('编辑数据格式无效。')
        ids=set()
        for column in model['columns']:
            if (not isinstance(column,dict) or set(column)!={'id','name','type'} or
                    not isinstance(column['id'],str) or not column['id'] or column['id'] in ids or
                    not isinstance(column['name'],str) or column['type'] not in {'text','number'}):
                raise ContractError('数据列无效。')
            ids.add(column['id'])
        if any(not isinstance(row,dict) for row in model['rows']):raise ContractError('数据行无效。')
        invalid=model.get('invalidCells',[])
        if not isinstance(invalid,list):raise ContractError('待修正数据无效。')
        for cell in invalid:
            if (not isinstance(cell,dict) or set(cell)!={'row','id','text'} or type(cell['row']) is not int or
                    not 0<=cell['row']<len(model['rows']) or cell['id'] not in ids or not isinstance(cell['text'],str)):
                raise ContractError('待修正数据无效。')
    def inline(value, depth=0):
        if depth>24:raise ContractError('文档内容层级过深。')
        if isinstance(value,dict):
            if value.get('type')=='blockReference':reference(value.get('props',{}))
            for key,item in value.items():
                if key=='href' and (not isinstance(item,str) or re.match(r'^\s*(?:javascript|data|vbscript):',item,re.I)):
                    raise ContractError('文档链接无效。')
                inline(item,depth+1)
        elif isinstance(value,list):
            for item in value:inline(item,depth+1)
    def blocks(items, depth=0, parent=None):
        if not isinstance(items, list) or depth > 12: raise ContractError('文档层级过深。')
        for block in items:
            if not isinstance(block, dict) or set(block)-{'id','type','props','content','children'}: raise ContractError('文档内容块无效。')
            key = block.get('id'); kind = block.get('type'); props = block.get('props', {})
            if not isinstance(key, str) or not key or key in seen or len(seen) >= 500: raise ContractError('文档内容块标识无效。')
            seen.add(key)
            if kind not in TEXT_TYPES | WIDGET_TYPES | EXTENDED_TYPES or not isinstance(props, dict): raise ContractError('不支持的文档内容块。')
            inline(block.get('content'))
            if kind=='markdown' and not isinstance(props.get('text'),str):raise ContractError('文档正文无效。')
            if any(not isinstance(v, (str, int, float, bool)) for v in props.values()): raise ContractError('内容块设置无效。')
            allowed = {'markdown': {'text'}, 'metric': {'label','value'},
                       'dataTable': {'source','title','data','dataKey'}, 'barChart': {'source','title','x','y','data','dataKey','chartType','unit'},
                       'jsonData': {'source','title'}}.get(kind)
            if allowed is not None and set(props)-allowed: raise ContractError('内容块包含不支持的设置。')
            if allowed is not None and any(not isinstance(v,str) for v in props.values()):raise ContractError('内容块设置应为文字。')
            if kind in {'dataTable','barChart'} and props.get('data'):
                data_model(props['data'])
            if kind in {'dataTable','barChart','jsonData'}:
                if props.get('source') and props['source'] not in sources:raise ContractError('内容块缺少数据快照。')
                if not props.get('source') and (kind=='jsonData' or not props.get('data')):raise ContractError('内容块缺少数据快照。')
            if kind=='barChart' and props.get('chartType','bar') not in {'bar','line','area'}:raise ContractError('图表类型无效。')
            if kind in {'dataTable','barChart'} and not props.get('data'):
                rows = sources[props['source']]['data']
                if not isinstance(rows, list) or len(rows)>5000 or any(not isinstance(row, dict) for row in rows): raise ContractError('表格或图表需要记录列表。')
                if kind=='barChart':
                    if not props.get('x') or not props.get('y') or any(props['x'] not in row or type(row.get(props['y'])) not in (int,float) for row in rows):
                        raise ContractError('图表需要实际的名称列与数值列。')
            if kind=='reference':reference(props)
            if kind=='math' and (set(props)!={'formula'} or not isinstance(props['formula'],str) or len(props['formula'])>20000):raise ContractError('公式内容无效。')
            if kind in {'image','video','file'}:
                if (set(props)-{'assetId','name','mime'} or any(not isinstance(v,str) for v in props.values()) or
                        props.get('assetId') and not re.fullmatch(r'[a-f0-9]{64}',props['assetId'])):raise ContractError('附件引用无效。')
            children=block.get('children',[])
            if kind=='columns' and (not isinstance(children,list) or len(children)!=2 or any(c.get('type')!='column' for c in children if isinstance(c,dict))):raise ContractError('分栏结构无效。')
            if kind=='column' and (parent!='columns' or not children):raise ContractError('分栏结构无效。')
            blocks(children, depth+1, kind)
    blocks(value['blocks'])
    if not seen: raise ContractError('文档内容不能为空。')
    return copy.deepcopy(value)


def encode(value):
    return json.dumps(validate(value), ensure_ascii=False, sort_keys=True, separators=(',', ':'))


def narrative(value):
    """Readable model context; the complete editable structure travels alongside it."""
    value=validate(value)
    def text(item):
        if isinstance(item,str):return item
        if isinstance(item,list):return ''.join(text(i) for i in item)
        if isinstance(item,dict):
            if 'text' in item:return str(item['text'])
            return text(item.get('content',item.get('rows',item.get('cells',[]))))
        return ''
    def lines(blocks):
        for block in blocks:
            props=block.get('props',{})
            if block['type']=='markdown':yield props.get('text','')
            elif block['type']=='metric':yield props.get('label','')+'：'+str(props.get('value',''))
            elif block['type'] in WIDGET_TYPES:yield props.get('title','')
            else:yield text(block.get('content',[]))
            yield from lines(block.get('children',[]))
    return '\n\n'.join(part for part in lines(value['blocks']) if part)


def write(core, *, name, document, document_id=None, base_revision=0, document_key=None, author='human', data_view=None, note=''):
    title = str(name or '').strip()
    if not title or len(title)>200: raise ContractError('请填写文档名称，最多200个字。')
    if type(base_revision) is not int or base_revision < 0: raise ContractError('请先读取当前文档再保存。')
    body = encode(document).encode()
    from .document_service import _normalize_agent_document_key, _normalize_document_data_view
    data_view=_normalize_document_data_view(data_view)
    with core.repository.definition_lock(), core.repository.connect() as c:
        current = None
        if document_id:
            chain = core._document_chain(c, document_id)
            if not chain: raise ContractError('文档不存在。')
            current = chain[-1]
        elif document_key:
            current = core._find_agent_document(c, document_key)
        meta = json.loads(current['meta_json']) if current else {}
        if data_view is None:data_view=meta.get('data_view')
        if current and (meta.get('content_model') != MODEL or not core.is_document_artifact(meta,current['name']) or current['trashed_at']):
            raise ContractError('这份内容不是当前文档格式，请新建文档。')
        revision = int(meta.get('revision') or 1) if current else 0
        from . import rich_document_assets
        asset_refs=rich_document_assets.references(core,validate(document),current['id'] if current else None)
        digest = hashlib.sha256(body).hexdigest()
        # A lost response can be retried without adding a revision.
        identical = current and digest == meta.get('sha256') and title == current['name'] and data_view == meta.get('data_view')
        if base_revision != revision and not identical:
            return {'ok': False, 'conflict': True, 'current_revision': revision,
                    'error': '文档已被更新。请先导出本页修改，再重新打开核对，避免覆盖他人的内容。'}
        if identical: return core.document_detail(current['id'], include_content=False)
        key = meta.get('document_key') or _normalize_agent_document_key(document_key or uuid.uuid4().hex, title)
        destination = core._agent_document_path(key, digest).with_suffix('.json')
        if not destination.exists(): destination.write_bytes(body)
        updated = {**meta, 'path': key+'.rich.json', 'content_model': MODEL, 'sha256': digest,
                   'size': len(body), 'revision': revision+1, 'document_key': key,
                   'source': meta.get('source','agent_chat'), 'purpose':'document', 'author':author,
                   'rich_asset_refs':asset_refs, 'data_view':data_view, 'note':str(note or '').strip()[:500],
                   **(core._document_employee_owner() if current is None else {})}
        root = int(meta.get('revision_of') or current['id']) if current else None
        if root: updated['revision_of'] = root
        row_id = c.execute('INSERT INTO artifacts(employee_run_id,name,ref,meta_json,created_at) VALUES(?,?,?,?,?)',
            (current['employee_run_id'] if current else None,title,str(destination),json.dumps(updated,ensure_ascii=False),utc_now())).lastrowid
        root = root or int(row_id)
        updated['revision_of'] = root
        c.execute('UPDATE artifacts SET meta_json=? WHERE id=?',(json.dumps(updated,ensure_ascii=False),row_id))
        core.repository.event('document:'+str(root),'document.revised' if current else 'document.created',
            {'document_id':int(row_id),'revision_of':root,'revision':revision+1,'content_model':MODEL},connection=c)
    return core.document_detail(row_id, include_content=False)
