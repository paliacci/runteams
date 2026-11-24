"""Scoped source/publication relationships; metadata never grants permission."""
from runteams_core.storage import device_data
from runteams_core.authoring.creator_contracts import canonical, strict_json
from runteams_core.authoring.source.creator_local_source import _read
from runteams_core.authoring.source.creator_source_revisions import Revisions
from runteams_core.authoring.source.source_io import atomic_json as atomic
from runteams_core.assets.asset_references import BusinessReference

LINK="employee-links.json"


def reference_key(value):
    ref=BusinessReference.from_json(value)
    if ref.resource!='employees':raise ValueError('员工关联类型无效。')
    return 'asset:'+canonical(ref.to_json()).decode()


def source_key(source_id,path):return 'source:'+source_id+':'+path


def links(store,source_id):
    store.check_scope();path=store._directory(source_id)/LINK
    if not path.exists():return {}
    value=strict_json(_read(path,65536))
    if (not isinstance(value,dict) or set(value)!={'schema','source_id','employees'} or
        value['schema']!='runteams.employee-links/v1' or value['source_id']!=source_id or
        not isinstance(value['employees'],dict)):raise ValueError('员工身份关联无效。')
    for entry,ref in value['employees'].items():
        if not isinstance(entry,str):raise ValueError('员工身份关联无效。')
        reference_key(ref)
    store.check_scope();return value['employees']


def link_source(store,source_id,mapping):
    """Called only after an authorized publication/source-acquisition receipt.

    A relation is navigation metadata, never a cached publication permission.
    Existing links cannot silently rebind to another employee or epoch.
    """
    revisions=Revisions(store,source_id)
    with revisions.locked():
        files=revisions._files(revisions._head());paths=strict_json(files['project.json'])['entrypoints']['employees']
        previous=links(store,source_id)
        scope=device_data.identity()
        for path,reference in mapping.items():
            if path not in paths:raise ValueError('员工关联源码入口无效。')
            reference_key(reference)
            if (reference['deployment_id']!=scope['deployment_id'] or reference['workspace_id']!=scope['account_id']):
                raise PermissionError('员工关联不属于当前源码账户。')
            if path in previous and previous[path]!=reference:raise ValueError('员工已经关联另一份资产。')
        value={**previous,**mapping};store.check_scope()
        atomic(revisions.root/LINK,{'schema':'runteams.employee-links/v1','source_id':source_id,'employees':value})
        store.check_scope()


def linked_sources(store, identities):
    """Resolve a batch in one pass through this workspace's source catalog."""
    matches = {}
    with store.reading_project() as reader:
        for source_id in reader.identities():
            for path, reference in links(reader, source_id).items():
                key = reference_key(reference)
                if key not in identities:
                    continue
                if key in matches:
                    raise ValueError('员工身份关联重复。')
                matches[key] = (source_id, path)
    return matches


def linked_source(store, reference):
    key = reference_key(reference)
    return linked_sources(store, {key}).get(key)
