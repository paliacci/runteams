"""Export committed content without an editor process."""
import json
from runteams_core.documents import rich_documents
from runteams_core.foundation.contracts import ContractError

MAX_EXPORT_BYTES=128*1024*1024


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
