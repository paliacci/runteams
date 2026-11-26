"""Export committed content without an editor process."""
from io import BytesIO
import json
from pathlib import Path, PureWindowsPath
import re
from zipfile import ZIP_DEFLATED, ZipFile
from runteams_core.documents import rich_documents
from runteams_core.foundation.contracts import ContractError

MAX_EXPORT_BYTES=128*1024*1024


def export_documents(core, identifiers):
    """Build one archive from the document library's current saved versions."""
    if not isinstance(identifiers, str) or not re.fullmatch(r'[1-9][0-9]{0,15}(?:,[1-9][0-9]{0,15}){0,999}', identifiers):
        raise ContractError('请选择最多 1000 份文档导出。')
    buffer = BytesIO()
    names = set()
    total = 0
    with core.repository.definition_lock(), core.repository.read_snapshot() as connection, \
            ZipFile(buffer, 'w', ZIP_DEFLATED) as archive:
        for identifier in dict.fromkeys(map(int, identifiers.split(','))):
            row = connection.execute('SELECT name,meta_json FROM artifacts WHERE id=? AND trashed_at IS NULL',
                                     (identifier,)).fetchone()
            if not row or not core.is_document_artifact(core._decode_meta(row['meta_json']), row['name']):
                raise ContractError('文档已不存在，请刷新文档列表。')
            detail = core.document_detail(identifier, refresh_task_report=False)
            raw, name, _ = export_document(core, detail)
            if detail['content_model'] != rich_documents.MODEL:
                suffix = Path(detail['path']).suffix.lower()
                if suffix in core.DOCUMENT_TEXT_SUFFIXES:
                    name = detail['name']
                    if not name.lower().endswith(suffix):
                        name += suffix
            stem, suffix = Path(name.replace('\\', '/')).name.rsplit('.', 1)
            stem = re.sub(r'[\x00-\x1f\x7f:*?"<>|]', '_', stem).strip(' .')
            stem = stem.encode('utf-16-le')[:320].decode('utf-16-le', 'ignore').rstrip(' .') or '文档'
            if PureWindowsPath(stem + '.' + suffix).is_reserved():
                stem = '_' + stem
            name = stem + '.' + suffix
            ordinal = 1
            while name.casefold() in names:
                ordinal += 1
                name = f'{stem} ({ordinal}).{suffix}'
            names.add(name.casefold())
            total += len(raw)
            if total > MAX_EXPORT_BYTES:
                raise ContractError('导出内容过大，请分批导出。')
            archive.writestr(name, raw)
    return buffer.getvalue(), 'RunTeams 文档.zip', 'application/zip'


def export_document(core, detail):
    if detail.get('content_model')==rich_documents.MODEL:
        value=rich_documents.validate(detail['content'])
        assets={}
        total=len(detail['content'].encode())
        def visit(blocks):
            nonlocal total
            from runteams_core.documents.rich_document_assets import read
            for block in blocks:
                identifier=block.get('props',{}).get('assetId') if block.get('type') in {'image','video','file'} else None
                if identifier and identifier not in assets:
                    file=read(core,detail['id'],identifier)
                    assets[identifier]={key:file[key] for key in ('name','type','data')}
                    total+=len(file['data'])+len(file['name'].encode())+len(file['type'])+256
                    if total>MAX_EXPORT_BYTES:raise ContractError('导出内容过大，请单独下载附件。')
                visit(block.get('children',[]))
        visit(value['blocks'])
        value['assets']=assets
        body=json.dumps(value,ensure_ascii=False,indent=2).encode()
        if len(body)>MAX_EXPORT_BYTES:raise ContractError('导出内容过大，请单独下载附件。')
        return (body,
                str(detail['name'])+'.json','application/json; charset=utf-8')
    # Ordinary source attachments remain downloadable in their own format.
    return detail['content'].encode(),str(detail['name'])+'.md','text/markdown; charset=utf-8'
