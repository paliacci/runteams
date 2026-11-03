"""Explicit read inputs over the original personal document/revision/export store.

Defaults select a document, admission freezes its immutable revision, and the
original exporter packages its own attachments. No cloud space, new document
store, write authority, executable view or caller-selected path is introduced.
"""
from contextlib import contextmanager
import hashlib
import re
from pathlib import Path
import tempfile
from runteams_core.storage import device_data
from runteams_core.foundation.identity.work_identity import schedule_binding

SELECTION='runteams.configuration-document-selection/1'
SNAPSHOT='runteams.configuration-document-snapshot/1'


def supports(field):
    binding=field.get('binding',{})
    return field.get('type')=='resource' and binding.get('provider')=='sdk_resource' and binding.get('resource_kind')=='document'


def _identifier(value):
    if type(value) is not int or not 1<=value<=2**53-1:raise ValueError('文档引用无效。')
    return value


@contextmanager
def _documents():
    from runteams_core.storage.storage_context import current_provider
    provider=current_provider();scope=device_data.identity()
    if not device_data.personal():raise PermissionError('请在当前个人资料库选择文档。')
    core=provider.device_work_service();core._actor()
    with core.repository.definition_lock():
        device_data.check(scope)
        yield scope,core
        if current_provider() is not provider:raise PermissionError('文档提供者已变化。')
        device_data.check(scope);core._actor()


def _latest(core,identifier):
    item=core.document_detail(_identifier(identifier),include_content=False)
    if not item or item.get('content_model')!='rich-document' or item.get('data_view'):
        raise ValueError('请选择当前资料库中可用的文档。')
    with core.repository.connect() as c:chain=core._document_chain(c,identifier)
    if not chain:raise ValueError('文档版本已不可用。')
    return core._document_root_id(chain[0]),item


def options(field):
    if not supports(field):raise ValueError('此项未声明文档资料。')
    with _documents() as (scope,core):
        result=[]
        for item in core.document_catalog(limit=200):
            if item.get('content_model')!='rich-document' or item.get('data_view'):continue
            root,current=_latest(core,item['id'])
            result.append({'schema':SELECTION,'owner':schedule_binding(scope),'document_id':root,'name':current['name']})
        return result


def _selection(scope,core,selection):
    if (not isinstance(selection,dict) or set(selection) not in ({'owner','document_id'},{'schema','owner','document_id','name'})
            or selection.get('schema',SELECTION)!=SELECTION):raise ValueError('请通过原资料选择入口选择文档。')
    if selection['owner']!=schedule_binding(scope):raise PermissionError('文档不属于当前资料库。')
    root,item=_latest(core,selection['document_id'])
    if root!=selection['document_id']:raise ValueError('请选择文档本身，不能将历史版本当作新资料。')
    return {'schema':SELECTION,'owner':schedule_binding(scope),'document_id':root,'name':item['name']}


def select(field,selection):
    if not supports(field):raise ValueError('此项未声明文档资料。')
    with _documents() as (scope,core):return _selection(scope,core,selection)


def _export(core,root,revision_id):
    _latest(core,root)
    with core.repository.connect() as c:chain=core._document_chain(c,root)
    if not any(row['id']==_identifier(revision_id) for row in chain):raise PermissionError('版本不属于所选文档。')
    item=core.historical_document_detail(revision_id)
    if not item or item.get('content_model')!='rich-document' or item.get('data_view'):raise ValueError('文档版本不可用。')
    from runteams_core.documents.document_export import export_document
    raw,_,_=export_document(core,item)
    return item,raw


def freeze(field,selection):
    if not supports(field):raise ValueError('此项未声明文档资料。')
    with _documents() as (scope,core):
        selection=_selection(scope,core,selection);root=selection['document_id'];_,latest=_latest(core,root)
        item,raw=_export(core,root,latest['id'])
        return {'schema':SNAPSHOT,'owner':schedule_binding(scope),'document_id':root,'revision_id':item['id'],
            'revision':item['revision'],'name':item['name'],'sha256':hashlib.sha256(raw).hexdigest()}


def verify_record(value,scope):
    """Portable identity/record validation, never current document access."""
    if not isinstance(value,dict) or set(value)!={'schema','owner','document_id','revision_id','revision','name','sha256'} or value['schema']!=SNAPSHOT:
        raise ValueError('文档工作快照无效。')
    if value['owner']!=schedule_binding(scope):raise PermissionError('文档不属于原资料库。')
    _identifier(value['document_id']);_identifier(value['revision_id'])
    if (type(value['revision']) is not int or value['revision']<1 or not isinstance(value['name'],str) or not 1<=len(value['name'])<=200
            or not isinstance(value['sha256'],str) or not re.fullmatch('[a-f0-9]{64}',value['sha256'])):raise ValueError('文档版本记录无效。')


def _frozen(scope,core,value):
    verify_record(value,scope)
    root=_identifier(value['document_id']);item,raw=_export(core,root,value['revision_id'])
    if type(value['revision']) is not int or item['revision']!=value['revision'] or item['name']!=value['name'] or hashlib.sha256(raw).hexdigest()!=value['sha256']:
        raise ValueError('原文档版本或附件已变化，请核对原工作。')
    return raw


def verify(field,value):
    if not supports(field):raise ValueError('此项未声明文档资料。')
    with _documents() as (scope,core):_frozen(scope,core,value)


def materialize(value,directory):
    with _documents() as (scope,core):raw=_frozen(scope,core,value)
    destination=Path(tempfile.mkdtemp(prefix='input-',dir=directory))/'document.json'
    destination.write_bytes(raw);destination.chmod(0o600)
    return {'provider':'sdk_resource','resource_kind':'document','name':value['name'],'document_id':value['document_id'],
        'revision_id':value['revision_id'],'revision':value['revision'],'sha256':value['sha256'],
        'path':str(destination),'access':'read-copy'}
