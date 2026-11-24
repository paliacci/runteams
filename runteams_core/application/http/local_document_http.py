"""Document-only ingress to shared services; never an employee/core API bridge."""
from dataclasses import dataclass
from pathlib import Path
import re
from runteams_core.foundation.contracts import ContractError


@dataclass
class DocumentResponse:
    payload: object
    status: int = 200
    filename: str = ''
    mime: str = ''


def handles(path):
    from runteams_core.pipelines.chat_delivery_export import PATH as delivery_export_path

    return bool(delivery_export_path.fullmatch(path)) or path in ('/api/device/work/trash', '/api/device/work/document-folders', '/api/device/work/documents/export') or bool(re.fullmatch(
        r'/api/(?:core|device/work)/(?:documents(?:/[1-9][0-9]*(?:/(?:download|assets(?:/[a-f0-9]{64})?|templates(?:/[a-f0-9]{64})?))?)?|artifacts/[1-9][0-9]*/(?:revisions|content|revert|trash|restore|delete))', path))


def dispatch(core, method, path, data):
    from runteams_core.documents import rich_documents, rich_document_assets as assets
    core._actor()
    from runteams_core.pipelines import chat_delivery_export
    match = chat_delivery_export.PATH.fullmatch(path)
    if match:
        if method != 'GET' or data:
            raise ContractError('工单交付下载请求无效。')
        raw = chat_delivery_export.download(core, int(match[1]), match[2])
        return DocumentResponse(raw, 200, chat_delivery_export.FILENAME, 'application/zip')
    if path == '/api/device/work/documents/export':
        if method != 'GET' or set(data) != {'ids'}:raise ContractError('文档导出范围无效。')
        from runteams_core.documents.document_export import export_documents
        raw, name, mime = export_documents(core, data['ids'])
        return DocumentResponse(raw, 200, name, mime)
    if path == '/api/device/work/document-folders':
        from runteams_core.documents import document_folders
        if method != 'POST':raise ContractError('不支持的文件夹操作。')
        return DocumentResponse(document_folders.mutate(core, data))
    if path == '/api/device/work/trash':
        if method != 'GET':raise ContractError('不支持的垃圾箱操作。')
        core.purge_expired_documents()
        from runteams_core.pipelines.pipeline_card_actions import trash_catalog
        from runteams_core.employees import source_employee_trash
        return DocumentResponse({'items': [*core.document_trash_catalog(), *trash_catalog(core), *source_employee_trash.catalog()], 'complete':True,
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
                return DocumentResponse({**item,'storage_scope':'device','device_page_ids':core.document_page_ids(item, identifier)} if item else {'error':'文档不存在'},200 if item else 404)
            if data.get('paged')=='1':
                options=dict(limit=int(data.get('limit',40)),query=data.get('q',''),cursor=data.get('cursor'),
                    sort=data.get('sort','created_at'),descending=data.get('direction','desc')=='desc')
                if path == '/api/device/work/documents' and 'folder' in data:
                    from runteams_core.documents import document_folders
                    result=document_folders.page(core,data['folder'],**options)
                else:
                    result=core.document_page(**options)
            else:result={'documents':core.document_catalog(int(data.get('limit',500)),data.get('q',''))}
        elif method == 'POST':
            if data.get('content_model') != rich_documents.MODEL or data.get('data_view'):
                raise ContractError('请使用当前文档格式保存。')
            options=dict(name=data.get('name'),document=data.get('document'),document_id=identifier,
                         document_key=data.get('document_key'),base_revision=data.get('base_revision',0))
            if path == '/api/device/work/documents' and 'folder' in data:
                from runteams_core.documents import document_folders
                result=document_folders.create_document(core,data['folder'],**options)
            else:
                result=rich_documents.write(core,**options)
            if result.get('conflict'):return DocumentResponse(result,409)
        else:raise ContractError('不支持的文档操作。')
    elif method=='GET' and action=='revisions':result={'revisions':core.document_revisions(identifier)}
    elif method == 'GET' and action == 'content' and set(data) == {'pdf_page'}:
        from runteams_core.documents.pdf_preview import PDFPreviewError, render_pdf_page

        artifact = core.artifact(identifier)
        if not artifact or artifact.get('trashed_at') or not artifact.get('ref'):
            return DocumentResponse({'error': 'unavailable'}, 404)
        try:
            path = Path(artifact['ref']).resolve(strict=True)
            if path.suffix.lower() != '.pdf' or not path.is_file() or not path.is_relative_to((Path(core.root) / 'artifacts').resolve()):
                return DocumentResponse({'error': 'unavailable'}, 404)
            return DocumentResponse(render_pdf_page(path, data['pdf_page']))
        except PDFPreviewError as error:
            return DocumentResponse({'error': str(error)}, 422)
        except OSError:
            return DocumentResponse({'error': 'unavailable'}, 404)
    elif method=='POST' and action=='content':
        with core.repository.definition_lock():
            detail=core.document_detail(identifier)
            if not detail or detail['content_model']!='table' or not detail['editable'] or set(data)!={'content'}:
                raise ContractError('这份表格无法编辑。')
            if detail['id']!=identifier:
                if detail['content']!=data['content']:
                    raise ContractError('表格已更新，请重新打开后核对。')
                result={'id':detail['id'],'created_revision':False}
            else:
                result=core.save_document_edit(identifier,data['content'])
            current=core.document_detail(result['id'],include_content=False)
            result.update(path=current['path'],revisions=core.document_revisions(result['id']))
    elif method=='POST' and action=='revert':
        new_id=core.revert_document(identifier)
        result={'id':new_id,'created_revision':True,'revisions':core.document_revisions(new_id)}
    elif method=='POST' and action in ('trash','restore','delete'):
        {'trash':core.trash_document,'restore':core.restore_document,'delete':core.delete_trashed_document}[action](identifier)
        result={'ok':True}
    else:raise ContractError('不支持的文档操作。')
    links = core.document_page_ids(result, identifier) if method == 'GET' else core.page_ids()
    return DocumentResponse({**result,'storage_scope':'device','device_page_ids':links},
                            201 if method=='POST' and not identifier else 200)
