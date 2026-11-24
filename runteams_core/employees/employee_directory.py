"""Single employee directory and SDK identity projection.

Source drafts, active releases and frozen work are different facts about one
employee. They are joined here by scoped references, never names or numeric
coincidences. This read model neither owns definitions nor grants execution.
"""

from contextlib import nullcontext
from copy import deepcopy
import stat
import json
from pathlib import Path
import sqlite3

from runteams_core.storage import device_data
from runteams_core.employees import source_employee_trash
from runteams_core.assets import source_links
from runteams_core.conversations.page_paths import asset_key, short_ids, page_id
from runteams_core.authoring.creator_contracts import canonical, strict_json
from runteams_core.authoring.source.creator_local_source import current_store, _read
from runteams_core.authoring.source.creator_source_revisions import Revisions
from runteams_core.assets.asset_references import BusinessReference

SCHEMA='runteams.employee-directory/v1'


def source_entries(store,source_id,*,sessions=(),display_only=False,pipeline_memberships=None,include_background=False):
    revisions=Revisions(store,source_id,display_only=display_only)
    with revisions.current_snapshot(display_only=display_only) as (revision, files):
        return _source_entries(store,source_id,revision,sessions,revisions.original['created_at'],files,pipeline_memberships,include_background)


def _overview_capabilities(files, directories):
    from runteams_core.assets.skills.skill_metadata import frontmatter

    capabilities = []
    for directory in directories if isinstance(directories, list) else []:
        if not isinstance(directory, str):
            continue
        try:
            extension = strict_json(files.get(directory + '/runteams.json', b'{}'))
            if not isinstance(extension, dict):
                continue
            work = extension.get('work') or {}
            if not isinstance(work, dict) or work.get('show_in_overview') is False:
                continue
            name, summary = work.get('name'), work.get('summary')
            if not name or not summary:
                markdown = files.get(directory + '/SKILL.md', b'')
                metadata = frontmatter(markdown.decode('utf-8'))
                name = name or extension.get('display_name') or metadata['name']
                summary = summary or metadata['description']
        except ValueError:
            continue
        if isinstance(name, str) and isinstance(summary, str) and name.strip() and summary.strip():
            capabilities.append({'name': name, 'summary': summary, 'objective': work.get('objective') or summary,
                                 'assets': work.get('assets', []), 'examples': work.get('examples', []),
                                 'package_key': directory.rsplit('/', 1)[-1], 'show_in_overview': bool(work)})
    return capabilities


def _employee_project(files):
    project=strict_json(files.get('project.json',b'null'))
    if (not isinstance(project,dict) or project.get('schema')!='runteams.creator-project/2'
            or not isinstance(project.get('entrypoints'),dict) or not isinstance(project['entrypoints'].get('employees'),list)
            or any(not isinstance(path,str) for path in project['entrypoints']['employees'])):
        raise ValueError('员工工程入口无效，请在原工程中修正。')
    return project


def _source_entries(store,source_id,revision,sessions,created_at,files,pipeline_memberships,include_background=False):
    project = _employee_project(files)
    from runteams_core.assets.skills.skill_metadata import declared_environment
    from runteams_core.employees.employee_references import source_reference
    paths=project['entrypoints']['employees'];bound=source_links.links(store,source_id)
    entries=[]
    for path in paths:
        employee=strict_json(files.get(path,b'null'))
        if (not isinstance(employee,dict) or not isinstance(employee.get('name'),str) or not employee['name'].strip()
                or not isinstance(employee.get('avatar',''),str)):
            raise ValueError('员工资源身份无效，请在原工程中修正。')
        matches=[session for session in sessions if
            (session.get('context') or {}).get('creator_local_source_id')==source_id and
            session['context'].get('creator_employee_source')==path]
        session=max(matches,key=lambda item:(str(item.get('updated_at','')),item['id']),default=None)
        from runteams_core.employees.employee_avatars import identity
        record={**identity(employee, files=files),'direct_assignment':False,'active_release':None}
        if include_background and session:
            from runteams_core.assets.workspace_background import display_fields
            record.update(display_fields(employee, files=files))
        directories=employee.get('skill_dirs')
        if isinstance(directories,list) and any(isinstance(directory,str) and files.get(directory+'/mcp/manifest.json')
                                                for directory in directories):
            record['local_mcp']=True
        environment = sorted({tool for directory in directories or [] if isinstance(directory, str)
                              for tool in declared_environment(files.get(directory + '/SKILL.md', b''))})
        entries.append({'key':source_links.source_key(source_id,path),'record':record,'asset':None,'work':None,
            'source':{'id':source_id,'path':path,'revision':revision,'version':project.get('version'),'description':employee.get('description',''),
                      **({'environment_tools': environment} if environment else {}),
                      'capabilities':_overview_capabilities(files,directories),'reference':source_reference(source_id,path),'chat_id':session['id'] if session else None,'target':(session or {}).get('context',{}).get('creator_source_target')},
            'reference':bound.get(path),'open':{'action':'source-work'},
            # A conversation can change the navigation target without changing roster order.
            'updated_at':created_at})
    if pipeline_memberships is not None:
        _collect_pipeline_memberships(source_id, project['entrypoints'].get('pipelines'), files, pipeline_memberships)
    return entries


def staffing_project(store, source_id):
    """Read only employee identities and team membership for the first-role picker."""
    revisions = Revisions(store, source_id, display_only=True)
    with revisions.current_snapshot(display_only=True) as (revision, files):
        paths = _employee_project(files)['entrypoints']
        employees = []
        for path in paths['employees']:
            employee = strict_json(files.get(path, b'null'))
            if not isinstance(employee, dict) or not isinstance(employee.get('name'), str) or not employee['name'].strip():
                raise ValueError('员工资源身份无效，请在原工程中修正。')
            employees.append([path, employee['name']])
        groups = {}
        _collect_pipeline_memberships(source_id, paths.get('pipelines'), files, groups)
    return revision, employees, groups


def _collect_pipeline_memberships(source_id, paths, files, groups):
    if not isinstance(paths, list):
        return
    for path in paths:
        if not isinstance(path, str):
            continue
        try:
            asset = strict_json(files.get(path, b'null'))
        except (ValueError, OSError):
            # A pipeline draft can be incomplete while its employees are available.
            continue
        if not isinstance(asset, dict) or asset.get('schema') != 'runteams.pipeline-source/3':
            continue
        pipeline, members = asset.get('pipeline'), asset.get('employees')
        name = pipeline.get('name') if isinstance(pipeline, dict) else None
        if not isinstance(name, str) or not name.strip() or not isinstance(members, list):
            continue
        group_key = source_links.source_key(source_id, path)
        for order, member in enumerate(members):
            if not isinstance(member, dict):
                continue
            source, pin = member.get('source'), member.get('dependency')
            if isinstance(source, str):
                key = source_links.source_key(source_id, source)
            elif (isinstance(pin, dict) and pin.get('kind') == 'source'
                    and isinstance(pin.get('source_id'), str) and isinstance(pin.get('employee_source'), str)):
                key = source_links.source_key(pin['source_id'], pin['employee_source'])
            else:
                continue
            groups.setdefault(key, {}).setdefault(group_key, {'key': group_key, 'name': name, 'order': order})


def for_session(session, *, include_background=False):
    context=session.get('context') or {};store=current_store(context['creator_local_scope'])
    rows=source_entries(store,context['creator_local_source_id'],sessions=[session],include_background=include_background)
    selected=context.get('creator_employee_source')
    rows=[row for row in rows if row['source']['path']==selected]
    if len(rows)!=1:raise ValueError('员工源码入口不匹配。')
    entry = rows[0]
    if _hidden_source_employee(store, entry['key']):
        entry['trashed'] = True
    return {**entry, 'page_id': page_id(entry['key'])}


def _hidden_team_members(store, source_id, hidden_paths):
    revisions = Revisions(store, source_id, display_only=True)
    with revisions.current_snapshot(display_only=True) as (_, files):
        paths = _employee_project(files)['entrypoints'].get('pipelines')
        groups = {}
        if isinstance(paths, list):
            selected = [path for path in paths if isinstance(path, str) and path in hidden_paths]
            _collect_pipeline_memberships(source_id, selected, files, groups)
        return groups


# Only membership is reusable. Direct trash and the latest hidden-team set
# are read on every request. A single immutable snapshot bounds retained data.
_hidden_members_snapshot = None


def _hidden_team_member_keys(store, paths):
    global _hidden_members_snapshot
    def fingerprint():
        return (store.root, tuple((source, tuple(sorted(paths[source])), Revisions.display_fingerprint(store, source))
                                  for source in sorted(paths)))

    store.check_scope()
    before = fingerprint()
    snapshot = _hidden_members_snapshot
    if snapshot is not None and snapshot[0] == before:
        store.check_scope()
        return snapshot[1]
    members = frozenset(key for source, selected in paths.items()
                        for key in _hidden_team_members(store, source, selected))
    if before == fingerprint():
        store.check_scope()
        _hidden_members_snapshot = before, members
    else:
        # A concurrent edit can change ownership. Reconcile through the roster.
        raise ValueError('员工所属团队已变化。')
    return members


def _hidden_source_employee(store, key):
    from runteams_core.pipelines import source_pipeline_trash
    if key in source_employee_trash.hidden_keys():
        return True
    hidden = source_pipeline_trash.hidden_source_references()
    paths = {}
    for ref in hidden:
        source_id = ref['source_id']
        paths.setdefault(source_id, set()).add(ref['pipeline_source'])
    try:
        if not paths or key not in _hidden_team_member_keys(store, paths):
            store.check_scope()
            return False
    except PermissionError:
        raise
    except (ValueError, OSError):
        pass
    # Another active team may still own this employee.
    return any(row['key'] == key and row.get('trashed') for row in local_entries(errors={}))


_roster_snapshot = None


def _roster_inputs(store):
    try:
        inputs = []
        for key in store.identities():
            link = store._directory(key) / source_links.LINK
            try:
                info = link.lstat()
            except FileNotFoundError:
                stamp = None
            else:
                if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
                    return None
                stamp = info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns
            inputs.append((key, Revisions.display_fingerprint(store, key), stamp))
        return inputs
    except (ValueError, OSError):
        # Let the normal catalog read report missing or invalid source data.
        return None


def _roster_sources(store, scope, errors):
    global _roster_snapshot
    inputs = _roster_inputs(store)
    signature = (store.root, scope, inputs)
    snapshot = _roster_snapshot
    if inputs is not None and snapshot is not None and snapshot[0] == signature:
        return deepcopy(snapshot[1])
    complete = True
    rows=[]
    groups = {}
    with store.reading_project() as reader:
        for source_id in reader.identities():
            try:
                rows.extend(source_entries(reader,source_id,display_only=True,
                                           pipeline_memberships=groups))
            except (ValueError,OSError) as exc:
                if errors is None:raise
                complete=False
                errors[source_id]={'error':str(exc)}
    if complete and inputs is not None and inputs == _roster_inputs(store):
        store.check_scope()
        _roster_snapshot = signature, deepcopy((rows, groups))
    return rows, groups


def local_entries(*,errors=None):
    if not device_data.personal():return []
    scope=device_data.identity();store=current_store(scope['cache_scope'])
    rows, groups = _roster_sources(store, scope, errors)
    # The latest conversation and trash state are independent of source revisions.
    latest = {}
    with device_data.connect(readonly=True) as connection:
        for row in connection.execute("SELECT id,context_json FROM chats WHERE kind='employee_design' ORDER BY updated_at,id"):
            context = json.loads(row['context_json'] or '{}')
            if isinstance(context, dict):
                source_id = context.get('creator_local_source_id')
                path = context.get('creator_employee_source')
                if isinstance(source_id, str) and isinstance(path, str):
                    latest[source_id, path] = row['id'], context.get('creator_source_target')
    for row in rows:
        source = row['source']
        source['chat_id'], source['target'] = latest.get((source['id'], source['path']), (None, None))
    apply_source_visibility(rows, groups)
    device_data.check(scope);return rows


def apply_source_visibility(rows, groups):
    from runteams_core.pipelines import source_pipeline_trash
    hidden_groups = source_pipeline_trash.hidden_source_keys() if groups else set()
    hidden = source_employee_trash.hidden_keys()
    for row in rows:
        if row['key'] in hidden:
            row['trashed'] = True
        if row['key'] in groups:
            memberships = groups[row['key']]
            active = [group for key, group in memberships.items() if key not in hidden_groups]
            row['pipeline_groups'] = active or list(memberships.values())
            if not active:
                row['trashed'] = True


def assemble(sources,assets,works):
    """Join sources and installed employees under their stable page identities."""
    # A trashed author's source must not hide a separately installed market copy.
    installed_market_refs = {source_links.reference_key(work['native_asset']['employee_reference'])
                             for work in works if (work.get('origin') or {}).get('kind') == 'marketplace'}
    rows={};by_ref={}
    for source in sources:
        if source.get('trashed') and not source.get('pipeline_groups') and source['reference'] and source_links.reference_key(source['reference']) in installed_market_refs:
            continue
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
    ids = short_ids(asset_key(row['key']) for row in rows.values())
    for row in rows.values():
        row['page_id'] = ids[asset_key(row['key'])]
    return sorted((row for row in rows.values() if not row.get('trashed')),key=lambda row:(str(row.get('updated_at','')),row['key']),reverse=True)


def read(**kwargs):
    from runteams_core.employees.employee_context import current
    return current().directory(**kwargs)


def with_activity(directory, active_turns):
    """Project active employee work and turns for the roster without reading work details."""
    from runteams_core.work.device_work import DeviceWorkStorage

    scope = device_data.identity()
    chats = []
    with (device_data.connect(readonly=True) if active_turns else nullcontext()) as connection:
        for chat_id, waiting in active_turns.items():
            session = connection.execute(
                "SELECT c.id,c.kind,c.employee_id,c.title,c.context_json, "
                "(SELECT m.id FROM chat_messages m WHERE m.chat_id=c.id ORDER BY m.id DESC LIMIT 1) AS last_message_id "
                "FROM chats c JOIN device_chat_index i ON i.chat_id=c.id "
                "WHERE c.id=? AND i.deleted=0 AND c.kind='general' AND c.subject_type='employee' AND c.scope_type='global'",
                (chat_id,)).fetchone()
            if not session:
                continue
            context = json.loads(session['context_json'] or '{}')
            if context.get('pipeline_work'):
                continue
            chats.append({**{key:session[key] for key in ('id','kind','employee_id','title','last_message_id')},
                          'storage_scope':'device','awaiting_reply':True,'awaiting_user_input':waiting,
                          'context':{key:context[key] for key in ('context_type','source_employee','employee_reference','target_employee_id',
                                                                 'creator_local_source_id','creator_employee_source') if key in context}})
    workflows, links = [], []
    try:
        storage = DeviceWorkStorage()
        storage.check_scope()
        if Path(storage.path).exists():
            with storage.connect(readonly=True) as connection:
                rows = connection.execute(
                    "SELECT w.id,w.state,w.updated_at,substr(t.title,1,100) AS task_title, "
                    "COALESCE(t.employee_reference,json_extract(w.snapshot_json,'$.employee_reference')) AS reference, "
                    "CASE WHEN t.employee_reference IS NULL THEN COALESCE((SELECT CAST(json_extract(p.value,'$.employee_id') AS INTEGER) "
                    " FROM json_each(w.snapshot_json,'$.definition.positions') p WHERE json_extract(p.value,'$.key')=w.cursor_key LIMIT 1), "
                    "(SELECT e.employee_id FROM employee_runs r JOIN employee_releases e ON e.id=r.employee_release_id "
                    " WHERE r.workflow_run_id=w.id AND r.id>COALESCE((SELECT max(CAST(json_extract(ev.data_json,'$.after_employee_run_id') AS INTEGER)) "
                    " FROM events ev WHERE ev.stream='workflow_run:'||w.id AND ev.type='workflow.task_recompiled'),0) "
                    " ORDER BY r.state='running' DESC,r.id DESC LIMIT 1),t.employee_id,0) ELSE 0 END AS occupying_employee_id, "
                    "i.identity FROM workflow_runs w JOIN tasks t ON t.id=w.task_id "
                    "LEFT JOIN device_work_resources i ON i.resource='workflow_runs' AND i.id=w.id "
                    "WHERE w.state IN ('ready','running','waiting_retry','needs_human','needs_approval','interrupted') "
                    "AND t.trashed_at IS NULL ORDER BY w.id DESC"
                )
                for row in rows:
                    workflows.append({**{key:row[key] for key in ('id','state','updated_at','task_title','occupying_employee_id')},
                                      'employee_reference':json.loads(row['reference']) if row['reference'] else None,
                                      'summary_only':True,'link_ready':bool(row['identity'])})
                    if row['identity']:
                        links.append({'resource':'workflows','id':str(row['id']),'public_id':'local-'+row['identity'].replace('-','')})
    except (ValueError,OSError,sqlite3.Error):
        directory['errors']['activity'] = {'error':'本机工作状态暂不可用。'}
        workflows, links = None, []
    device_data.check(scope)
    return {**directory,'activity':{'chats':chats,'workflows':workflows},'device_page_ids':links}


def open_entry(data):
    if (not isinstance(data,dict) or set(data)-{'key','runtime','operation_id'} or not {'key','runtime'}<=set(data) or not isinstance(data['runtime'],dict)
            or set(data['runtime'])-{'channel_id','model','reasoning_effort'}):raise ValueError('员工入口参数无效。')
    key=data['key']
    parts=key.split(':',2) if isinstance(key,str) else []
    if len(parts)!=3 or parts[0]!='source':
        raise PermissionError('员工不存在或当前账号不可访问。')
    scope=device_data.identity();store=current_store(scope['cache_scope'])
    try:
        entry=next((row for row in source_entries(store,parts[1]) if row['key']==key),None)
    except FileNotFoundError:
        entry=None
    if entry and _hidden_source_employee(store, key):
        raise ValueError('这名员工已移到垃圾箱，请先恢复。')
    if entry is None:raise PermissionError('员工不存在或当前账号不可访问。')
    from runteams_core.authoring.creator_local_authoring import session_for
    from runteams_core.employees.employee_session_view import public_session
    session = session_for(store, entry['source']['id'], scope['cache_scope'], data['runtime'],
                          employee_source=entry['source']['path'], title=entry['record']['name'],
                          operation_id=data.get('operation_id'))
    return {'session':public_session(session)}
