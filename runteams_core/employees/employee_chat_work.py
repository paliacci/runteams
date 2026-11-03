from runteams_core.foundation.identity.work_identity import principal
"""SDK employee assignments in the existing device task/run ledger.

An assignment freezes a complete source reference and runtime package, never an
employee row. Execution consumes the original Chat handler and its native SDK
permissions. Unknown/started admissions are inspected, never automatically sent
again. Existing pipeline and compiled release execution is unchanged.
"""
from runteams_core.employees import employee_work_contracts
from runteams_core.employees import employee_acquisition_refs
from runteams_core.assets import rented_references
import json
from pathlib import Path

from runteams_core.storage import device_data
from runteams_core.foundation.contracts import ContractError
from runteams_core.employees.employee_references import checked_reference, same
from runteams_core.storage.repository import utc_now


def snapshot(core, identifier):
    with core.repository.connect() as c:
        row = c.execute('SELECT snapshot_json FROM workflow_runs WHERE id=?', (identifier,)).fetchone()
    value = json.loads(row[0]) if row else {}
    return value if value.get('schema') == employee_work_contracts.SCHEMA else None


def catalog(reference, *, limit=100, core=None):
    reference = checked_reference(reference)
    from runteams_core.employees.employee_binding import related_references
    owners=related_references(reference)
    if core is None:
        from runteams_core.work.device_work import database_path
        if not database_path().is_file():
            return []
        from runteams_core.work.device_work_services import current
        core = current()
    result = []
    with core.repository.connect() as c:
        rows = c.execute('SELECT wr.id,wr.state,wr.snapshot_json,wr.updated_at,t.id AS task_id,t.title '
            'FROM workflow_runs wr JOIN tasks t ON t.id=wr.task_id WHERE t.trashed_at IS NULL '
            'ORDER BY wr.updated_at DESC,wr.id DESC').fetchall()
    for row in rows:
        value = json.loads(row['snapshot_json'])
        owner=value.get('employee_reference')
        belongs=owner and any(same(owner,ref) for ref in owners)
        if not belongs and value.get('pipeline_work'):
            belongs=any(any(same(item['snapshot'].get('employee_reference'),ref) for ref in owners)
                for item in value.get('pipeline_history',[]))
        if not owner:
            with core.repository.connect() as connection:
                refs=connection.execute("SELECT rel.source_ref_json FROM workflow_runs wr,json_each(wr.snapshot_json,'$.definition.positions') p JOIN employee_releases rel ON rel.id=json_extract(p.value,'$.employee_release_id') WHERE wr.id=?",(row['id'],)).fetchall()
            belongs=any(any(same(native,ref) for ref in owners) for item in refs if (native:=json.loads(item[0]).get('native_asset',{}).get('employee_reference')))
        if belongs:
            result.append({'id': row['id'], 'workflow_id': row['id'], 'task_id': row['task_id'],
                'title': row['title'], 'state': row['state'], 'updated_at': row['updated_at'],
                'employee_reference': reference, 'chat_id': value.get('work_chat_id'),
                'storage_scope': 'device'})
            if len(result) >= min(max(int(limit), 1), 500):
                break
    return result


def submit(core, binding, action, source):
    from runteams_core.employees.source_employee_runtime import validate
    package = validate(binding['package'])
    reference = checked_reference(binding['reference'])
    title = str(action.get('title') or '').strip()
    objective = str(action.get('objective') or '').strip()
    if not title or not objective:
        raise ContractError('请提供工作名称和目标。')
    if action.get('employee') not in (None, '', binding['employee']['name']):
        raise PermissionError('当前工作不能更换员工。')
    if action.get('employee_reference') is not None and not same(action['employee_reference'], reference):
        raise PermissionError('当前工作不能更换员工。')
    payload = {key: action.get(key) for key in ('context', 'parameters', 'inputs',
        'asset_bindings', 'module_bindings', 'local_reference_ids', 'skill_key') if key in action}
    payload.update(schema='runteams.task-input/v2', objective=objective)
    if isinstance(payload.get('context'),str):payload['context']={'brief':payload['context']}
    if action.get('acceptance'):
        payload.setdefault('context',{})['acceptance']=action['acceptance']
    prior_id=action.get('source_run_id')
    if prior_id is not None:
        if type(prior_id) is not int or prior_id<1:raise ContractError('历史工作引用无效。')
        previous=next((job for job in catalog(reference,core=core,limit=500) if job['id']==prior_id and job['state']=='completed'),None)
        if previous is None:raise PermissionError('请选择这名员工已完成的原工作。')
        # Historical context is selected explicitly. It never becomes a new
        # execution identity or an implicit asset grant.
        payload.setdefault('context',{})['previous_work']={
            'workflow_id':prior_id,'employee_reference':reference,
            'results':results(core,reference,workflow_id=prior_id)['results']}

    for field,default in [('context',{}),('parameters',{}),('inputs',[]),('asset_bindings',{}),('module_bindings',{})]:payload.setdefault(field,default)
    if payload.get('module_bindings') or any(payload['context'].get(field) for field in ('business_event','work_item')):
        raise ContractError('这项共享业务工作尚未接入本机执行。')
    from runteams_core.authoring.definition_contracts import validate_definition
    # User references are validated by the original composer boundary below;
    # they are not additional fields of the frozen task payload contract.
    payload.pop('local_reference_ids', None)
    payload = validate_definition('task_payload', payload)
    if payload.get('skill_key'):
        from runteams_core.employees.source_employee_runtime import units, package_asset
        selected=next((unit for unit in units(package_asset(package)) if unit['key']==payload['skill_key']),None)
        if selected is None:raise ContractError('所选工作不属于当前员工运行包。')
        from jsonschema import Draft202012Validator
        errors=list(Draft202012Validator(selected['input_schema']).iter_errors(payload['parameters']))
        if errors:raise ContractError('工作输入不符合技能声明：'+errors[0].message)
    from runteams_core.employees.employee_context import current
    bindings, files = current().prepare_task_references(action,source,core=core)
    payload['asset_bindings'].update({key: str(value) for key, value in bindings.items()})
    payload['inputs'].extend({'name': item['name'], 'asset_grant_id': str(item['grant_id'])} for item in files)
    dedupe = str(action.get('dedupe_key') or '').strip()
    with core.repository.connect() as c:
        if dedupe:
            for row in c.execute('SELECT wr.id,wr.task_id,wr.snapshot_json,t.title FROM workflow_runs wr '
                    'JOIN tasks t ON t.id=wr.task_id WHERE t.opportunity_key=?', (dedupe,)):
                previous = json.loads(row['snapshot_json'])
                if previous.get('employee_reference') and same(previous['employee_reference'], reference):
                    return _effect(binding, row['title'], row['task_id'], row['id'])
        now = utc_now()
        frozen = {'schema': employee_work_contracts.SCHEMA, 'employee_reference': reference, 'package': package,
            'employee': {key: binding['employee'][key] for key in ('name', 'avatar')},
            'name': binding['employee']['name'], 'definition': {'positions': [], 'edges': []},
            'source': {'chat_id': source['chat_id'], 'actor_id': principal(device_data.identity())}}
        from runteams_core.configuration.employee_configuration import for_package
        from runteams_core.employees.source_employee_runtime import package_asset
        if package_asset(package)['employee'].get('configuration'):
            frozen['configuration'] = for_package(package).snapshot()
        from runteams_core.conversations.conversation_folders import frozen_reference
        folder_reference = frozen_reference(source['chat_id'])
        if folder_reference:
            frozen['work_folder'] = folder_reference
        task = c.execute('INSERT INTO tasks(pipeline_id,employee_id,employee_reference,opportunity_key,title,payload_json,state,'
            'pipeline_snapshot_json,created_at,updated_at) VALUES(NULL,NULL,?,?,?,?,?,?,?,?)',
            (json.dumps(reference,sort_keys=True,separators=(',',':')),dedupe or None, title, json.dumps(payload), 'ready', json.dumps(frozen), now, now)).lastrowid
        run = c.execute('INSERT INTO workflow_runs(task_id,state,available_at,cursor_key,snapshot_json,created_at,updated_at) '
            'VALUES(?,?,?,?,?,?,?)', (task, 'ready', now, 'employee', json.dumps(frozen), now, now)).lastrowid
        core.repository.event('task:'+str(task), 'task.created', {'task_id': task,
            'employee_reference': reference, 'title': title}, connection=c)
        core.repository.event('workflow_run:'+str(run), 'workflow.created', {'task_id': task,
            'employee_reference': reference}, connection=c)
    return _effect(binding, title, task, run)


def _effect(binding, title, task, run):
    return '已交给「{}」处理「{}」'.format(binding['employee']['name'], title), {
        'run_card': {'workflow_id': run, 'task_id': task, 'title': title, 'state': 'ready',
                     'storage_scope': 'device', 'employee_reference': binding['reference']}}


def execute(core, identifier, frozen, runtime=None):
    if not frozen.get('pipeline_work'):
        return _execute(core, identifier, frozen, runtime)
    # Source pipeline stages use this exact employee runner. Pre-send failures
    # block the admitted work; an already sent/unknown turn is never replayed.
    from runteams_core.pipelines import source_pipeline_control as control
    from runteams_core.pipelines.source_pipeline_flow import RecoveryPending
    token = control.begin_execution(core, identifier)
    if token is None:
        control.settle_pause(core, frozen['pipeline_work']['reference'])
        return core.workflow(identifier)['state']
    try:
        from runteams_core.pipelines.source_pipeline_work import verify_context
        verify_context(frozen['pipeline_work'], frozen['package'], read_build=True)
        if frozen.get('configuration') is not None:
            from runteams_core.configuration.employee_configuration import validate_snapshot
            validate_snapshot(frozen['package'], frozen['configuration'])
        return _execute(core, identifier, frozen, runtime)
    except RecoveryPending:
        return core.workflow(identifier)['state']
    except Exception as error:
        with core.repository.connect() as connection:
            row = connection.execute('SELECT state,snapshot_json FROM workflow_runs WHERE id=?', (identifier,)).fetchone()
        if row['state'] in ('completed', 'failed', 'canceled'):
            return row['state']
        current=json.loads(row['snapshot_json'])
        if current.get('pipeline_visit')!=frozen.get('pipeline_visit'):return row['state']
        if current.get('pipeline_submission') and not current.get('pipeline_applied_result'):
            from runteams_core.pipelines.source_pipeline_flow import defer_settlement
            return defer_settlement(core,identifier,current['pipeline_visit'],error)
        admitted = json.loads(row['snapshot_json']).get('send_admitted')
        return finish(core, identifier, 'interrupted' if admitted else 'blocked', str(error),visit=frozen.get('pipeline_visit'))
    finally:
        control.end_execution(core, identifier, token)


def _execute(core, identifier, frozen, runtime=None):
    """One admitted send through the original handler; no model retry engine."""
    from runteams_core.employees.source_employee_runtime import validate, create_chat
    validate(frozen['package'])
    executor = getattr(core, 'chat_executor', None)
    if not callable(executor):
        raise ContractError('原员工工作宿主尚未就绪。')
    if frozen.get('pipeline_work') and frozen.get('pipeline_result_correction'):
        from runteams_core.pipelines.source_pipeline_flow import correct_rejected_result
        return correct_rejected_result(core,identifier,executor)
    with core.repository.connect() as c:
        row = c.execute('SELECT wr.*,t.payload_json,t.title FROM workflow_runs wr '
            'JOIN tasks t ON t.id=wr.task_id WHERE wr.id=?', (identifier,)).fetchone()
        frozen = json.loads(row['snapshot_json'])
        # The admission is committed BEFORE sending. Any pre-existing admission
        # represents an unknown/started effect and must not trigger another send.
        if row['state']!='running':return row['state']
        if frozen.get('send_admitted'):
            return finish(core, identifier, 'interrupted',
                '原工作结果需要核对，请查看工作记录。' if frozen.get('pipeline_work') else '原工作结果需要核对，请查看工作对话。',visit=frozen.get('pipeline_visit'))
        payload = json.loads(row['payload_json'])
        work_context={'employee_work':{'workflow_id':identifier,'task_id':row['task_id']},
            'pipeline_work':frozen['pipeline_work'],'pipeline_generation':frozen['pipeline_generation']} if frozen.get('pipeline_work') else None
        chat_id = frozen.get('work_chat_id') or create_chat(frozen['package'], title=row['title'],preferred_skill=payload.get('skill_key'),
            configuration_snapshot=frozen.get('configuration'),**({'work_context':work_context} if work_context else {}))
        frozen['work_chat_id'] = chat_id
        c.execute('UPDATE workflow_runs SET snapshot_json=? WHERE id=?', (json.dumps(frozen), identifier))
    if frozen.get('work_folder'):
        from runteams_core.conversations.conversation_folders import inherit
        inherit(chat_id, frozen['work_folder'])
    from runteams_core.storage import product_store
    with device_data.connect() as connection:
        session=product_store.get_chat(chat_id,include_messages=False)
        if frozen.get('pipeline_work'):
            employee_work_contracts.verify_prepared_session(frozen,session,identifier,row['task_id'])
        context=session['context'];context['employee_work']={'workflow_id':identifier,'task_id':row['task_id']}
        if frozen.get('pipeline_work'):
            context['pipeline_work'] = frozen['pipeline_work']
            context['pipeline_generation'] = frozen.get('pipeline_generation')
        connection.execute('UPDATE chats SET context_json=? WHERE id=?',(json.dumps(context),chat_id))
    payload = json.loads(row['payload_json'])
    if frozen.get('pipeline_work'):
        from runteams_core.employees.employee_context import current as employee_context
        try:employee_context().prepare_work(core,chat_id,frozen)
        except employee_work_contracts.WorkPreparationRequired as error:
            with core.repository.connect() as connection:
                current=connection.execute('SELECT snapshot_json FROM workflow_runs WHERE id=?',(identifier,)).fetchone()
                waiting=json.loads(current[0])
                if waiting.get('pipeline_visit')!=frozen['pipeline_visit'] or waiting.get('send_admitted'):
                    raise ContractError('原岗位已经变化，请核对当前工作。') from error
                waiting['pipeline_setup_required']={'chat_id':chat_id,'message':str(error)[:1000]}
                connection.execute('UPDATE workflow_runs SET snapshot_json=? WHERE id=?',(json.dumps(waiting),identifier))
            raise
        frozen.pop('pipeline_setup_required',None)
    from runteams_core.employees.employee_workspaces import workspace
    from runteams_core.work import task_inputs
    from runteams_core.conversations.conversation_folders import runtime as folder_runtime
    work_root = Path(folder_runtime(chat_id, workspace(chat_id)))
    payload['inputs']=task_inputs.materialize(core.root,row['task_id'],payload.get('inputs'),work_root,core.root/'runteams.db')
    grants={}
    if payload.get('asset_bindings') or any('asset_grant_id' in item for item in payload.get('inputs') or []):
        from runteams_core.employees.source_employee_runtime import package_asset
        from runteams_core.authoring.creator_conversation_assets import extension
        slots=[]
        if payload.get('skill_key'):
            selected=next((extension(b).get('work') for b in package_asset(frozen['package'])['skill_bundles'] if b['package_key']==payload['skill_key']),None)
            if selected is None:raise ContractError('所选工作不属于当前员工运行包。')
            slots=selected.get('assets') or []
        if runtime is None:raise ContractError('原工作资料授权器尚未就绪。')
        blocked,records,grants=runtime._mount_assets({'selected_work':{'work':{'assets':slots}}},
            {'task':{'payload':payload}},work_root,lambda *_:None)
        if blocked:return finish(core,identifier,'blocked',str(records.get('output',{}).get('question','工作资料需要核对。')),visit=frozen.get('pipeline_visit'))
        payload['local_assets']=records
    with core.repository.connect() as connection:
        if frozen.get('pipeline_work'):
            current = connection.execute('SELECT state,snapshot_json FROM workflow_runs WHERE id=?', (identifier,)).fetchone()
            if current['state'] != 'running' or json.loads(current['snapshot_json']).get('send_admitted'):
                return current['state']
        frozen['send_admitted']=True
        order={'schema':'runteams.employee-chat-order/v1','employee_reference':frozen['employee_reference'],
               'package':frozen['package'],'payload':payload,'chat_id':chat_id}
        position_key = 'employee'
        if frozen.get('pipeline_work'):
            order['pipeline_work'] = frozen['pipeline_work']
            order['pipeline_generation'] = frozen.get('pipeline_generation')
            order['pipeline_visit'] = frozen['pipeline_visit']
            position_key = frozen['pipeline_work']['position_key']
        attempt=connection.execute('SELECT COUNT(*)+1 FROM employee_runs WHERE workflow_run_id=? AND position_key=?',(identifier,position_key)).fetchone()[0] if frozen.get('pipeline_work') else 1
        frozen['employee_run_id']=connection.execute('INSERT INTO employee_runs(workflow_run_id,position_key,employee_release_id,attempt,state,input_json,output_json,created_at,updated_at) VALUES(?,?,NULL,?,?,?,?,?,?)',
            (identifier,position_key,attempt,'running',json.dumps(order),'{}',utc_now(),utc_now())).lastrowid
        connection.execute('UPDATE workflow_runs SET snapshot_json=? WHERE id=?',(json.dumps(frozen),identifier))
    prompt = payload['objective']
    details = {key: value for key, value in payload.items() if key not in ('schema', 'objective') and value}
    if details:
        prompt += '\n\n工作资料：\n' + json.dumps(details, ensure_ascii=False)
    result = executor(chat_id, prompt, core._cancel_event(identifier), 'employee-work:'+str(identifier))
    if grants:
        from runteams_core.assets import local_assets
        changed=[name for name,entry in grants.items() if local_assets.diff_fingerprints(entry['before'],local_assets.fingerprint(entry['grant']))]
        if changed:
            result=('blocked','工作资料已变化，请核对：'+'、'.join(changed))
            if frozen.get('pipeline_work'):
                from runteams_core.pipelines.source_pipeline_flow import invalidate_result
                invalidate_result(core,identifier,frozen['pipeline_visit'],result[1])
    return finish(core, identifier, *result,visit=frozen.get('pipeline_visit'))


def finish(core, identifier, status, reason='', *, visit=None):
    frozen=snapshot(core,identifier)
    if frozen and frozen.get('pipeline_work'):
        from runteams_core.pipelines.source_pipeline_flow import finish_turn
        return finish_turn(core,identifier,status,reason,expected_visit=visit)
    states = {'completed': 'completed', 'failed': 'failed', 'blocked': 'needs_human',
              'cancelled': 'canceled', 'canceled': 'canceled', 'interrupted': 'interrupted'}
    state = states.get(status, 'interrupted')
    with core.repository.connect() as c:
        row = c.execute('SELECT task_id,state,snapshot_json FROM workflow_runs WHERE id=?', (identifier,)).fetchone()
        if row['state'] == 'canceled':
            state = 'canceled'
        frozen=json.loads(row['snapshot_json']);execution_state=state
        if frozen.get('pipeline_work'):
            from runteams_core.pipelines.source_pipeline_control import read, TERMINAL
            if read(core,frozen['pipeline_work']['reference'],c)['status']=='paused' and state not in TERMINAL:
                frozen['pipeline_pause']={'previous_state':state};state='paused'
        now = utc_now()
        c.execute('UPDATE workflow_runs SET state=?,updated_at=? WHERE id=?', (state, now, identifier))
        c.execute('UPDATE tasks SET state=?,updated_at=? WHERE id=?', (state, now, row['task_id']))
        if frozen.get('pipeline_work'):
            c.execute('UPDATE workflow_runs SET snapshot_json=? WHERE id=?',(json.dumps(frozen),identifier))
        if frozen.get('employee_run_id'):
            from runteams_core.storage import product_store
            session=product_store.get_chat(frozen.get('work_chat_id')) or {}
            reply=next((m.get('text') or '' for m in reversed(session.get('messages') or []) if m['role']=='bot'),'')
            output={'status':execution_state,'summary':reply,'output':{},'issues':[reason] if reason else [],'artifacts':[]}
            c.execute('UPDATE employee_runs SET state=?,output_json=?,updated_at=? WHERE id=?',
                (execution_state,json.dumps(output),now,frozen['employee_run_id']))
        core.repository.event('workflow_run:'+str(identifier), 'workflow.'+state,
            {'reason': reason}, connection=c)
    return state


def documents(core,reference,workflow_id=None):
    from runteams_core.employees.employee_binding import related_references
    reference=checked_reference(reference);owners=related_references(reference)
    rows=[];seen=set()
    with core.repository.connect() as connection:
        values=connection.execute('SELECT a.*,r.employee_release_id,r.workflow_run_id AS run_workflow_id FROM artifacts a LEFT JOIN employee_runs r ON r.id=a.employee_run_id WHERE a.trashed_at IS NULL ORDER BY a.id DESC').fetchall()
        releases=connection.execute('SELECT id,employee_id,source_ref_json FROM employee_releases').fetchall()
    release_ids=set();asset_ids=set()
    for release in releases:
        native=json.loads(release['source_ref_json']).get('native_asset',{}).get('employee_reference')
        if native and any(same(native,ref) for ref in owners):
            release_ids.add(release['id']);asset_ids.add(release['employee_id'])
    for row in values:
        meta=json.loads(row['meta_json']);owner=meta.get('employee_reference')
        belongs=any(same(owner,ref) for ref in owners) if owner else row['employee_release_id'] in release_ids or meta.get('source')=='employee_run' and meta.get('employee_id') in asset_ids
        owning_work=meta.get('workflow_id') or meta.get('workflow_run_id') or row['run_workflow_id']
        if not belongs or workflow_id is not None and owning_work!=workflow_id:continue
        root=meta.get('revision_of') or row['id']
        if root in seen:continue
        seen.add(root);rows.append({**dict(row),'meta_json':meta,'size':meta.get('size'),
            'purpose':meta.get('purpose'),'workflow_id':owning_work,'storage_scope':'device'})
    return rows


def detail(core,identifier):
    with core.repository.connect() as connection:
        run=connection.execute('SELECT * FROM workflow_runs WHERE id=?',(identifier,)).fetchone()
        task=connection.execute('SELECT * FROM tasks WHERE id=?',(run['task_id'],)).fetchone()
        attempts=connection.execute('SELECT * FROM employee_runs WHERE workflow_run_id=? ORDER BY id DESC',(identifier,)).fetchall()
    frozen=json.loads(run['snapshot_json'])
    if frozen.get('schema')!=employee_work_contracts.SCHEMA:return core.workflow(identifier)
    artifacts=documents(core,frozen['employee_reference'],identifier)
    owned={canonical_reference(frozen['employee_reference']):artifacts}
    if frozen.get('pipeline_work'):
        for attempt in attempts:
            reference=json.loads(attempt['input_json'])['employee_reference'];key=canonical_reference(reference)
            if key not in owned:owned[key]=documents(core,reference,identifier)
        artifacts=list({item['id']:item for items in owned.values() for item in items}.values())
    decoded=[]
    for attempt in attempts:
        item=dict(attempt);item['input_json']=json.loads(item['input_json']);item['output_json']=json.loads(item['output_json'])
        reference=item['input_json'].get('employee_reference',frozen['employee_reference']) if frozen.get('pipeline_work') else frozen['employee_reference']
        if frozen.get('pipeline_work'):
            versions=[frozen]+[h['snapshot'] for h in frozen.get('pipeline_history',[])]
            original=next((v for v in versions if v['pipeline_visit']==item['input_json']['pipeline_visit']
                and v['employee_reference']==reference),None)
            if original is None:raise ContractError('岗位尝试缺少原员工版本记录。')
            item['employee_name']=original['employee']['name']
        item['artifacts']=owned.get(canonical_reference(reference),artifacts);item['work']={'employee_reference':reference,'objective':item['input_json']['payload']['objective']}
        decoded.append(item)
    return {**dict(run),'snapshot_json':frozen,'task':{**dict(task),'payload_json':json.loads(task['payload_json'])},
        'employee_runs':decoded,'artifacts':artifacts,'team_parameters':{},'events':core.repository.events('workflow_run:'+str(identifier)),'storage_scope':'device'}


def canonical_reference(reference):
    return json.dumps(reference,sort_keys=True,separators=(',',':'))


def delivery(core, job, reports):
    from runteams_core.work.result_views import delivery_view, output_fields
    from runteams_core.work.work_reports import apply_to_delivery
    work=detail(core,job['id']);attempts=[]
    for run in work['employee_runs']:
        output=run['output_json'];attempts.append({**run,'employee_name':run.get('employee_name',work['snapshot_json']['employee']['name']),
            'summary':output.get('summary',''),'issues':output.get('issues',[]),
            'output':output.get('output') or {}, 'work_done':output.get('work_done') or [],
            'fields':output_fields(output['output'],{}) if output.get('output') else [],'actions':[]})
    return apply_to_delivery(core,delivery_view({**job,'created_at':work['created_at'],'updated_at':work['updated_at'],'attempts':attempts},[]),reports)


def results(core,reference,workflow_id=None):
    from runteams_core.work.result_views import delivery_view, output_fields
    jobs=catalog(reference,core=core,limit=500);deliveries=[]
    from runteams_core.work.work_reports import catalog as report_catalog, apply_to_delivery
    report_groups={}
    for report in report_catalog(core):report_groups.setdefault(report['binding'].get('workflow_id'),[]).append(report)
    for job in jobs:
        if workflow_id is not None and job['id']!=workflow_id:continue
        if snapshot(core,job['id']) is None:
            deliveries.extend(core.contextual_results(workflow_id=job['id'])['results']);continue
        deliveries.append(delivery(core,job,report_groups.get(job['id'],[])))
    from runteams_core.work.work_reports import standalone_results
    deliveries.extend(standalone_results(core,reference))
    deliveries.sort(key=lambda item:item['updated_at'],reverse=True)
    return {'schema':'runteams.result-view/v1','scope':{'employee_reference':checked_reference(reference)},'results':deliveries}
