"""Document-only ingress to shared services; never an employee/core API bridge."""
from dataclasses import dataclass
import re
from runteams_core.foundation.contracts import ContractError


@dataclass
class DocumentResponse:
    payload: object
    status: int = 200
    filename: str = ''
    mime: str = ''


def handles(path):
    return path == '/api/device/work/trash' or bool(re.fullmatch(
        r'/api/(?:core|device/work)/(?:documents(?:/[1-9][0-9]*(?:/(?:download|assets(?:/[a-f0-9]{64})?|templates(?:/[a-f0-9]{64})?))?)?|artifacts/[1-9][0-9]*/(?:revisions|revert|trash|restore|delete))', path))


def dispatch(core, method, path, data):
    from runteams_core.documents import rich_documents, rich_document_assets as assets
    core._actor()
    if path == '/api/device/work/trash':
        if method != 'GET':raise ContractError('不支持的垃圾箱操作。')
        core.purge_expired_documents()
        return DocumentResponse({'items': core.document_trash_catalog(), 'complete':True,
                                 'storage_scope':'device','device_page_ids':core.page_ids()})
    suffix = path.split('/',4)[4] if path.startswith('/api/device/work/') else path[len('/api/core/'):]
    parts = suffix.split('/'); resource=parts[0]
    identifier = int(parts[1]) if len(parts)>1 else None
    action = parts[2] if len(parts)>2 else None
    if resource == 'documents':
        if action == 'download':
            if method != 'GET':raise ContractError('导出只支持读取。')
            from runteams_core.documents.document_export import export_document
            item=core.document_detail(identifier)
            if not item:return DocumentResponse({'error':'文档不存在'},404)
            raw,name,mime=export_document(core,item)
            return DocumentResponse(raw,200,name,mime)
        if action in ('assets','templates'):
            key=parts[3] if len(parts)>3 else None
            if action=='assets' and method=='POST' and not key:result=assets.upload(core,identifier,data.get('file'))
            elif action=='assets' and method=='GET' and key:result=assets.read(core,identifier,key)
            elif action=='templates' and method=='GET':result={'fragment':assets.template(core,identifier,key)} if key else {'templates':assets.templates(core,identifier)}
            elif action=='templates' and method=='POST' and not key:result=assets.save_template(core,identifier,data.get('name'),data.get('fragment'))
            else:raise ContractError('不支持的文档资料操作。')
            return DocumentResponse(result,201 if method=='POST' else 200)
        if method == 'GET':
            if identifier:
                item=core.historical_document_detail(identifier) if data.get('historical')=='1' else core.document_detail(identifier)
                return DocumentResponse({**item,'storage_scope':'device','device_page_ids':core.page_ids()} if item else {'error':'文档不存在'},200 if item else 404)
            if data.get('paged')=='1':
                result=core.document_page(limit=int(data.get('limit',40)),query=data.get('q',''),cursor=data.get('cursor'),
                    sort=data.get('sort','created_at'),descending=data.get('direction','desc')=='desc')
            else:result={'documents':core.document_catalog(int(data.get('limit',500)),data.get('q',''))}
        elif method == 'POST':
            if data.get('content_model') != rich_documents.MODEL or data.get('data_view'):
                raise ContractError('请使用当前文档格式保存。')
            result=rich_documents.write(core,name=data.get('name'),document=data.get('document'),
                document_id=identifier,document_key=data.get('document_key'),base_revision=data.get('base_revision',0))
            if result.get('conflict'):return DocumentResponse(result,409)
        else:raise ContractError('不支持的文档操作。')
    elif method=='GET' and action=='revisions':result={'revisions':core.document_revisions(identifier)}
    elif method=='POST' and action=='revert':
        new_id=core.revert_document(identifier)
        result={'id':new_id,'created_revision':True,'revisions':core.document_revisions(new_id)}
    elif method=='POST' and action in ('trash','restore','delete'):
        {'trash':core.trash_document,'restore':core.restore_document,'delete':core.delete_trashed_document}[action](identifier)
        result={'ok':True}
    else:raise ContractError('不支持的文档操作。')
    return DocumentResponse({**result,'storage_scope':'device','device_page_ids':core.page_ids()},
                            201 if method=='POST' and not identifier else 200)
