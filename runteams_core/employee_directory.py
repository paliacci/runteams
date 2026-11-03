"""Single employee directory and SDK identity projection.

Source drafts, active releases and frozen work are different facts about one
employee. They are joined here by scoped references, never names or numeric
coincidences. This read model neither owns definitions nor grants execution.
"""

from . import device_data, source_links
from .creator_contracts import canonical, strict_json
from .creator_local_source import current_store, _read
from .creator_source_revisions import Revisions
from runteams_core.asset_references import BusinessReference

SCHEMA='runteams.employee-directory/v1'


def source_entries(store,source_id,*,sessions=()):
    revisions=Revisions(store,source_id);files=revisions.files()
    project=strict_json(files.get('project.json',b'null'))
    if (not isinstance(project,dict) or project.get('schema')!='runteams.creator-project/2'
            or not isinstance(project.get('entrypoints'),dict) or not isinstance(project['entrypoints'].get('employees'),list)
            or any(not isinstance(path,str) for path in project['entrypoints']['employees'])):
        raise ValueError('员工工程入口无效，请在原工程中修正。')
    from .source_employee_runtime import reference
    paths=project['entrypoints']['employees'];bound=source_links.links(store,source_id)
    entries=[]
    for path in paths:
        employee=strict_json(files.get(path,b'null'))
        if (not isinstance(employee,dict) or not isinstance(employee.get('name'),str) or not employee['name'].strip()
                or not isinstance(employee.get('avatar',''),str)):
            raise ValueError('员工资源身份无效，请在原工程中修正。')
        matches=[session for session in sessions if
            (session.get('context') or {}).get('creator_local_source_id')==source_id and
            (session['context'].get('creator_employee_source')==path or len(paths)==1)]
        session=max(matches,key=lambda item:(str(item.get('updated_at','')),item['id']),default=None)
        from .employee_avatars import identity
        record={**identity(employee, files=files),'direct_assignment':False,'active_release':None}
        entries.append({'key':source_links.source_key(source_id,path),'record':record,'asset':None,'work':None,
            'source':{'id':source_id,'path':path,'reference':reference(source_id,path),'chat_id':session['id'] if session else None,'target':(session or {}).get('context',{}).get('creator_source_target')},
            'reference':bound.get(path),'open':{'action':'source-work'},
            'updated_at':(session or {}).get('updated_at',revisions.original['created_at'])})
    return entries


def for_session(session):
    context=session.get('context') or {};store=current_store(context['creator_local_scope'])
    rows=source_entries(store,context['creator_local_source_id'],sessions=[session])
    selected=context.get('creator_employee_source')
    rows=[row for row in rows if row['source']['path']==selected] if selected else rows
    if len(rows)!=1:raise ValueError('员工源码入口不匹配。')
    return rows[0]


def local_entries(*,errors=None):
    if not device_data.personal():return []
    import product_store
    scope=device_data.identity();store=current_store(scope['cache_scope']);sessions=[]
    # Conversations only supply a navigation target, never employee identity.
    with device_data.connect(readonly=True) as connection:
        ids=[row[0] for row in connection.execute("SELECT id FROM chats WHERE kind='employee_design'")]
    for cid in ids:
        session=product_store.get_chat(cid,include_messages=False)
        if session is not None:sessions.append(session)
    rows=[];after=None
    while True:
        page=store.list(after)
        for source in page['items']:
            try:rows.extend(source_entries(store,source['id'],sessions=sessions))
            except (ValueError,OSError) as exc:
                if errors is None:raise
                errors[source['id']]={'error':str(exc)}
        after=page['next_cursor']
        if after is None:break
    device_data.check(scope);return rows


def assemble(sources,assets,works):
    """Pure identity join used by every caller; no UI-specific side lists."""
    rows={};by_ref={}
    for source in sources:
        key=source['key']
        if key in rows:raise ValueError('员工源码身份重复。')
        rows[key]=dict(source)
        if source['reference']:
            ref=source_links.reference_key(source['reference'])
            if ref in by_ref:raise ValueError('同一资产关联多份员工源码，请先修正关联。')
            by_ref[ref]=key
    for asset in assets:
        ref=source_links.reference_key(asset['reference']);key=by_ref.get(ref,ref)
        row=rows.setdefault(key,{'key':key,'source':None,'work':None,'reference':asset['reference']})
        display={**asset,**({key:row['record'].get(key) for key in ('name','avatar','avatar_src')} if row.get('source') else {})}
        row.update(asset=asset,record=display,open={'action':'work','employee_id':asset['id']},updated_at=asset.get('updated_at',''))
        by_ref[ref]=key
    for work in works:
        ref=work.get('native_asset',{}).get('employee_reference')
        if ref is None:raise ValueError('员工工作缺少原 SDK 资产身份。')
        identity=source_links.reference_key(ref);key=by_ref.get(identity,identity)
        row=rows.setdefault(key,{'key':key,'source':None,'asset':None,'reference':ref})
        row.update(work=work,open={'action':'work','employee_id':work['id']})
        if not row.get('asset'):
            display={**work,**({key:row['record'].get(key) for key in ('name','avatar','avatar_src')} if row.get('source') else {})}
            row.update(record=display,updated_at=work.get('updated_at',''))
        by_ref[identity]=key
    return sorted(rows.values(),key=lambda row:(str(row.get('updated_at','')),row['key']),reverse=True)


def read(**kwargs):
    from .employee_context import current
    return current().directory(**kwargs)


def open_entry(data):
    if (not isinstance(data,dict) or set(data)-{'key','runtime','purpose','operation_id'} or not {'key','runtime'}<=set(data) or not isinstance(data['runtime'],dict)
            or set(data['runtime'])-{'channel_id','model','reasoning_effort'}):raise ValueError('员工入口参数无效。')
    entry=next((row for row in local_entries() if row['key']==data['key']),None)
    if entry is None:raise PermissionError('员工不存在或当前账号不可访问。')
    purpose=data.get('purpose','work')
    if purpose not in ('work','settings') or 'operation_id' in data and purpose!='work':raise ValueError('员工入口用途无效。')
    from runteams_core.employee_session_view import public_session
    if purpose=='work':
        from .source_employee_runtime import reference,open_default,open_work
        ref=reference(entry['source']['id'],entry['source']['path'])
        session=open_work(ref,data['operation_id']) if 'operation_id' in data else open_default(ref)
    else:
        scope=device_data.identity();store=current_store(scope['cache_scope'])
        from .creator_local_authoring import session_for
        session=session_for(store,entry['source']['id'],scope['cache_scope'],data['runtime'],employee_source=entry['source']['path'])
    return {'session':public_session(session)}
