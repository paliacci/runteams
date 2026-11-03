"""Explicit SDK collection read inputs over the original typed collection history.

This grants neither local collection CRUD nor any cloud SDK namespace access.
Only the user chooses the original collection, and work fixes its record versions.
"""
import hashlib
import re
import tempfile
from pathlib import Path
from . import device_data
from .local_collections import Collections
from .work_identity import schedule_binding

SELECTION='runteams.configuration-collection-selection/1'
SNAPSHOT='runteams.configuration-collection-snapshot/1'

def supports(field):
    binding=field.get('binding',{})
    return field.get('type')=='resource' and binding.get('provider')=='sdk_resource' and binding.get('resource_kind')=='collection'

def _selection(value,scope):
    if (not isinstance(value,dict) or set(value)!={'schema','owner','collection_id','model_sha256','name'} or value.get('schema')!=SELECTION):
        raise ValueError('请从原资料入口选择数据集合。')
    if value['owner']!=schedule_binding(scope):raise PermissionError('集合不属于当前资料库。')
    return {key:value[key] for key in ('collection_id','model_sha256','name')}

def options(field):
    if not supports(field):raise ValueError('此项未声明集合资料。')
    store=Collections()
    return [{'schema':SELECTION,'owner':schedule_binding(store.scope),**row} for row in store.input_options()]

def select(field,value):
    if not supports(field):raise ValueError('此项未声明集合资料。')
    store=Collections();selected=store.select_input(_selection(value,store.scope))
    return {'schema':SELECTION,'owner':schedule_binding(store.scope),**selected}

def freeze(field,value):
    if not supports(field):raise ValueError('此项未声明集合资料。')
    store=Collections();selected,versions,raw=store.freeze_input(_selection(value,store.scope))
    return {'schema':SNAPSHOT,'owner':schedule_binding(store.scope),**selected,'record_versions':versions,'sha256':hashlib.sha256(raw).hexdigest()}

def verify_record(value,scope):
    if (not isinstance(value,dict) or set(value)!={'schema','owner','collection_id','model_sha256','name','record_versions','sha256'} or value['schema']!=SNAPSHOT):raise ValueError('集合资料快照无效。')
    if value['owner']!=schedule_binding(scope):raise PermissionError('集合不属于原资料库。')
    from uuid import UUID
    if not isinstance(value['collection_id'],str) or str(UUID(value['collection_id']))!=value['collection_id']:raise ValueError('原集合引用无效。')
    if (not isinstance(value['name'],str) or not 1<=len(value['name'])<=80
            or any(not isinstance(value[k],str) or not re.fullmatch('[a-f0-9]{64}',value[k]) for k in ('model_sha256','sha256'))
            or not isinstance(value['record_versions'],list)):raise ValueError('原集合资料记录无效。')
    previous=None
    for row in value['record_versions']:
        if (not isinstance(row,dict) or set(row)!={'key','revision'} or not isinstance(row['key'],str)
                or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9:._/-]{0,239}',row['key'])
                or type(row['revision']) is not int or row['revision']<1 or previous is not None and row['key']<=previous):raise ValueError('原集合记录版本无效。')
        previous=row['key']

def _raw(value):
    store=Collections();verify_record(value,store.scope)
    selected={key:value[key] for key in ('collection_id','model_sha256','name')}
    raw=store.export_input(selected,value['record_versions'])
    if hashlib.sha256(raw).hexdigest()!=value['sha256']:raise ValueError('原集合记录内容已变化，请核对原工作。')
    return raw

def verify(field,value):
    if not supports(field):raise ValueError('此项未声明集合资料。')
    _raw(value)

def materialize(value,directory):
    raw=_raw(value);destination=Path(tempfile.mkdtemp(prefix='input-',dir=directory))/'collection.json'
    destination.write_bytes(raw);destination.chmod(0o600)
    return {'provider':'sdk_resource','resource_kind':'collection','name':value['name'],'collection_id':value['collection_id'],
        'model_sha256':value['model_sha256'],'record_count':len(value['record_versions']),'sha256':value['sha256'],'path':str(destination),'access':'read-copy'}
