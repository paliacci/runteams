"""Typed handoffs in the original employee work ledger, never a model runner.

Employees submit professional results. Only the host selects declared edges,
accepts inputs, owns the cursor, and creates the next visit of the SAME work.
"""
from runteams_core.pipelines import pipeline_references
import copy
import json
import uuid
import hashlib

from runteams_core.pipelines import source_pipeline_work as work, source_pipeline_control as control
from runteams_core.work import workflow_policy
from runteams_core.foundation.contracts import ContractError, normalize_work_result
from runteams_core.authoring.creator_contracts import canonical, digest
from runteams_core.storage.repository import utc_now

INPUT_SCHEMA = {'type': 'object', 'properties': {
    'operation': {'type': 'string', 'enum': ['read', 'submit', 'read_report']},
    'operation_id': {'type': 'string'}, 'report_id': {'type': 'integer', 'minimum': 1},
    'result': {'type': 'object', 'properties': {
        'status': {'type': 'string', 'enum': ['completed','blocked','needs_human','failed']},
        'summary': {'type': 'string'}, 'output': {'type': 'object'},
        'issues': {'type': 'array', 'items': {'type': 'string'}},
        'schema': {'type':'string','enum':['runteams.work-result/v1']},
        'artifacts': {'type':'array','maxItems':0}, 'actions': {'type':'array','maxItems':0},
        'work_done': {'type':'array','maxItems':3,'items':{'type':'string'}}},
        'required': ['status'], 'additionalProperties': False,
        'description': 'Submission envelope. Put every field from output_schema inside result.output, never directly in result. Save the formal report separately first.'}}, 'required': ['operation'], 'additionalProperties': False}


def result_schema(package,context):
    value=copy.deepcopy(INPUT_SCHEMA['properties']['result'])
    unit=declared(package,work._position(context['asset'],context['position_key'])[0]['skill_key'])
    value['allOf']=[{'if':{'properties':{'status':{'const':'completed'}},'required':['status']},
        'then':{'required':['summary','output'],'properties':{'output':
            copy.deepcopy(unit['output_schema']) if unit else {'type':'object'}}}}]
    return value


class RecoveryPending(ContractError):
    """Only platform settlement remains; do not run the model again."""


def defer_settlement(core,identifier,visit,error):
    message=str(error)[:1000]
    with core.repository.connect() as connection:
        row=_row(connection,identifier);pending=json.loads(row['snapshot_json'])
        if pending['pipeline_visit']!=visit or row['state'] in control.TERMINAL:return row['state']
        if not pending.get('pipeline_recovery_pending') or pending.get('pipeline_program_error')!=message:
            pending.update(pipeline_recovery_pending=True,pipeline_program_error=message)
            _save(core,connection,row,pending,'blocked')
            core.repository.event('workflow_run:'+str(identifier),'workflow.settlement_pending',{'message':message},connection=connection)
        core.__dict__.setdefault('_pending_pipeline_recoveries',set()).add(identifier)
        return connection.execute('SELECT state FROM workflow_runs WHERE id=?',(identifier,)).fetchone()[0]


def declared(package, key):
    from runteams_core.employees.employee_context import current as employee_context
    from runteams_core.authoring.creator_conversation_assets import extension
    bundle = next(b for b in employee_context().package_asset(package)['skill_bundles'] if b['package_key'] == key)
    return extension(bundle).get('work')


def archive(frozen):
    return frozen.get('pipeline_history', []) + [{'snapshot': copy.deepcopy({
        k: v for k, v in frozen.items() if k not in ('pipeline_history', 'pipeline_execution')})}]


def _row(connection, identifier):
    row = connection.execute('SELECT w.*,t.payload_json,t.trashed_at FROM workflow_runs w '
        'JOIN tasks t ON t.id=w.task_id WHERE w.id=?', (identifier,)).fetchone()
    if row is None or row['trashed_at']:
        raise ContractError('原流水线工作不存在。')
    return row


def _save(core, connection, row, frozen, state, cursor=None, payload=None):
    if state not in control.TERMINAL and state!='paused' and control.read(core,frozen['pipeline_work']['reference'],connection)['status']=='paused':
        frozen['pipeline_pause']={'previous_state':state};state='paused'
    now = utc_now(); encoded = canonical(frozen).decode()
    connection.execute('UPDATE workflow_runs SET snapshot_json=?,state=?,cursor_key=?,available_at=?,updated_at=? WHERE id=?',
        (encoded, state, cursor or row['cursor_key'], now if state == 'ready' else None, now, row['id']))
    connection.execute('UPDATE tasks SET employee_reference=?,pipeline_snapshot_json=?,state=?,updated_at=? WHERE id=?',
        (canonical(frozen['employee_reference']).decode(), encoded, state, now, row['task_id']))
    if payload is not None:
        connection.execute('UPDATE tasks SET payload_json=? WHERE id=?', (canonical(payload).decode(), row['task_id']))


def _runs(connection, frozen, extra=None):
    rows = []
    for identifier in frozen.get('pipeline_lineage', []):
        row = connection.execute('SELECT id,position_key,state,output_json FROM employee_runs WHERE id=?', (identifier,)).fetchone()
        if row:
            rows.append({**dict(row), 'output_json': json.loads(row['output_json'])})
    if extra:
        rows.append(extra)
    return rows


def _report_ref(core,item):
    from runteams_core.work.work_reports import reference
    document=core.document_detail(item['id'],include_content=False)
    artifact=core.artifact(document['id'])
    return {**reference(item),'artifact_id':artifact['id'],'sha256':artifact['meta_json']['sha256']}


def _own_report_runs(frozen,role=None,history=None):
    """Read prior accepted reports without restoring obsolete output values."""
    context=role['context'] if role else frozen['pipeline_work']
    employee=role['package']['reference'] if role else frozen['employee_reference']
    history=frozen.get('pipeline_history',[]) if history is None else history
    return {prior['employee_run_id'] for entry in history
        for prior in [entry.get('snapshot') or {}]
        if prior.get('employee_run_id') and prior.get('pipeline_applied_result')
        and prior['pipeline_visit']<frozen['pipeline_visit']
        and prior.get('pipeline_submission') and prior.get('employee_reference')==employee
        and (prior.get('pipeline_work') or {}).get('reference')==context['reference']
        and (prior.get('pipeline_work') or {}).get('position_key')==context['position_key']}


def _reports(core,connection,frozen,role=None):
    result=[]
    allowed=set(frozen.get('pipeline_lineage',[]))|_own_report_runs(frozen,role)|{(frozen.get('pipeline_feedback') or {}).get('employee_run_id')}
    for identifier in sorted(i for i in allowed if i):
        row=connection.execute('SELECT output_json FROM employee_runs WHERE id=?',(identifier,)).fetchone()
        if row:result.extend(json.loads(row[0]).get('report_references',[]))
    if frozen.get('pipeline_submission'):
        result.extend(frozen['pipeline_submission'].get('reports',[]))
    elif frozen.get('employee_run_id'):
        from runteams_core.work.work_reports import catalog
        result.extend(_report_ref(core,r) for r in catalog(core) if r['binding'].get('employee_run_id')==frozen['employee_run_id'])
    return list({r['id']:r for r in result}.values())


def verify_links(connection,identifier,frozen,order=None,*,history=None):
    """Backup validation grants no new live access and does not follow paths."""
    owned=set(frozen.get('pipeline_lineage',[]))|_own_report_runs(frozen,history=history)|{frozen.get('employee_run_id'),
        (frozen.get('pipeline_feedback') or {}).get('employee_run_id'),(frozen.get('pipeline_waiting') or {}).get('source_run_id')}
    references=list((frozen.get('pipeline_submission') or {}).get('reports',[]))
    if order:references+=(order.get('payload') or {}).get('context',{}).get('pipeline_stage',{}).get('reports',[])
    for run_id in owned-{None}:
        if type(run_id) is not int:raise ContractError('交接岗位引用无效。')
        row=connection.execute('SELECT workflow_run_id,output_json FROM employee_runs WHERE id=?',(run_id,)).fetchone()
        if row is None or row[0]!=identifier:raise ContractError('交接记录引用了其他工作。')
        references+=json.loads(row[1]).get('report_references',[])
    for ref in references:
        if not isinstance(ref,dict) or type(ref.get('artifact_id')) is not int:raise ContractError('交接汇报引用无效。')
        row=connection.execute('SELECT meta_json FROM artifacts WHERE id=?',(ref['artifact_id'],)).fetchone()
        meta=json.loads(row[0]) if row else {};binding=meta.get('work_report') or {}
        if (binding.get('workflow_id')!=identifier or binding.get('employee_run_id') not in owned or
                meta.get('revision_of')!=ref.get('id') or meta.get('revision',1)!=ref.get('revision') or meta.get('sha256')!=ref.get('sha256')):
            raise ContractError('交接汇报版本或工作归属不一致。')


def parameters(core, connection, frozen, position_key, package, extra=None):
    asset = frozen['pipeline_work']['asset']; original = frozen['pipeline_input']
    if asset['pipeline'].get('parameters'):
        values = core._collect_team_parameter_values(asset['pipeline'], original, _runs(connection, frozen, extra))
    else:
        values = copy.deepcopy(original.get('parameters', {}))
    position, _ = work._position(asset, position_key)
    unit = declared(package, position['skill_key'])
    return core._pipeline_work_parameters({'work': unit or {'input_schema': {'type': 'object'}}},
        asset['pipeline'], position_key, values)


def payload_for(core, connection, frozen, role, extra=None):
    context = role['context']; key = context['position_key']
    payload = copy.deepcopy(frozen['pipeline_input'])
    payload['parameters'] = parameters(core, connection, frozen, key, role['package'], extra)
    payload['skill_key'] = work._position(context['asset'], key)[0]['skill_key']
    payload = work.stage_payload(role['package'], context, payload, updating=True)
    stage = payload['context']['pipeline_stage']
    stage['handoff_owner'] = 'host_after_acceptance'
    stage['downstream_positions'] = [e['to'] for e in context['asset']['pipeline']['edges'] if e['from'] == key]
    stage['result_submission'] = 'Use runteams_pipeline_work read, then submit a typed result before finishing. A chat reply is not a handoff.'
    stage['reports']=_reports(core,connection,frozen,role)
    if frozen.get('pipeline_feedback'):
        stage['feedback'] = copy.deepcopy(frozen['pipeline_feedback'])
    if frozen.get('pipeline_response'):
        stage['human_response'] = frozen['pipeline_response']
    stage['standards'] = [copy.deepcopy(s) for s in context['asset']['pipeline'].get('standards', [])
        if not s.get('employee_refs') or work._position(context['asset'], key)[1]['ref'] in s['employee_refs']]
    return payload


def initial(core, connection, role, bundle, payload,start_column_key=None):
    frozen = work.stage_snapshot(role['package'], role['context'], role['configuration'])
    frozen.update(pipeline_generation=bundle['generation'], pipeline_visit=1,
        pipeline_input=copy.deepcopy(payload), pipeline_lineage=[])
    if payload.get('skill_key') not in (None,'',work._position(role['context']['asset'],role['context']['position_key'])[0]['skill_key']):
        raise ContractError('工作技能必须使用流水线岗位绑定。')
    declarations = bundle['asset']['pipeline'].get('parameters', [])
    if declarations:
        allowed = {p['key'] for p in declarations if p.get('source') == 'user' and p['type'] != 'secret'}
        if set(payload.get('parameters', {})) - allowed:
            raise ContractError('任务只能提供已声明的用户参数，员工产出不能由任务创建者代填。')
    entry=start_column_key or workflow_policy.start_position(bundle['asset']['pipeline'])
    if next(p for p in bundle['asset']['pipeline']['positions'] if p['key']==entry)['kind']=='approval':
        return frozen,copy.deepcopy(payload)
    return frozen, payload_for(core, connection, frozen, role)


def _result(package, context, result):
    if not isinstance(result,dict) or set(result)-{'schema','status','summary','output','artifacts','issues','work_done','actions'}:
        raise ContractError('岗位结果包含未声明字段。result 必须包含 status、summary、output；技能 output_schema 的字段全部放在 result.output 内，不能直接放在 result。')
    value = normalize_work_result(result)
    if not isinstance(value['output'], dict) or value['artifacts'] or value.get('actions'):
        raise ContractError('岗位结果使用结构化 output；文档由正式汇报保存，不接收自行授予权限的成果或动作。')
    if value['status'] == 'completed':
        unit = declared(package, work._position(context['asset'], context['position_key'])[0]['skill_key'])
        if unit:
            from jsonschema import Draft202012Validator
            error = next(Draft202012Validator(unit['output_schema']).iter_errors(value['output']), None)
            if error:
                raise ContractError('岗位产出不符合技能声明：' + error.message)
    return value


def _rejected_completed_submission(core,connection,frozen):
    """Only a host-recorded completed turn and a rejected schema are repairable.

    Missing/truncated/unknown turns and accepted results never authorize another
    send. Revalidate the original arguments; model prose is not a receipt.
    """
    from runteams_core.storage import product_store
    if frozen.get('pipeline_submission') or frozen.get('pipeline_applied_result'):
        return None
    session=product_store.get_chat(frozen.get('work_chat_id')) or {}
    context=session.get('context') or {}
    if (context.get('pipeline_work')!=frozen.get('pipeline_work') or
            context.get('pipeline_generation')!=frozen.get('pipeline_generation')):
        return None
    if (frozen.get('pipeline_result_correction')or{}).get('native_proof'):
        from runteams_core.pipelines.pipeline_context import current as pipeline_context
        return pipeline_context().attested_proof(core,connection,frozen,session)
    messages=session.get('messages') or []
    if not messages or messages[-1]['role']!='bot':return None
    message=messages[-1];metadata=message.get('metadata') or {};trace=metadata.get('trace') or {}
    if (not trace.get('complete') or any(trace.get(k) for k in ('failed','cancelled','truncated'))
            or metadata.get('pending') or metadata.get('incomplete')):
        return None
    for item in reversed(trace.get('events') or []):
        event=item.get('event') or {};meta=event.get('meta') or {};args=meta.get('arguments') or {}
        if (event.get('kind')!='step' or event.get('status')!='failed'
                or meta.get('tool')!='runteams_pipeline_work' or args.get('operation')!='submit'):
            continue
        operation=args.get('operation_id')
        try:
            if str(uuid.UUID(operation))!=operation:return None
        except (ValueError,TypeError,AttributeError):return None
        if connection.execute("SELECT 1 FROM events WHERE stream=? AND type='pipeline.result_submitted'",
                ('source-pipeline-result:'+operation,)).fetchone():return None
        try:_result(frozen['package'],frozen['pipeline_work'],args.get('result'))
        except ContractError as error:
            # This exact validator must explain the host-recorded rejection.
            # The expanded envelope diagnostic also recognizes its old prefix;
            # no old submission format is accepted or transformed.
            text=str(error);recorded=event.get('output') or ''
            if not recorded or not text.startswith(recorded):return None
            return {'message_id':message['id'],'trace_sha256':digest(trace),
                    'submission_id':operation,'error':text}
        return None
    return None


def _queue_result_correction(core,connection,row,frozen):
    if frozen.get('pipeline_result_correction'):return False
    proof=_rejected_completed_submission(core,connection,frozen)
    if not proof:return False
    frozen['pipeline_result_correction']={**proof,'admitted':False}
    frozen.pop('pipeline_unresolved',None)
    _save(core,connection,row,frozen,'ready')
    core.repository.event('workflow_run:'+str(row['id']),'workflow.result_correction_queued',
        {'visit':frozen['pipeline_visit'],'message_id':proof['message_id'],
         'submission_id':proof['submission_id']},connection=connection)
    return True


def correct_rejected_result(core,identifier,executor):
    """One new correction turn in the original chat, never the old work prompt."""
    with core.repository.connect() as connection:
        row=_row(connection,identifier);frozen=json.loads(row['snapshot_json'])
        repair=frozen.get('pipeline_result_correction') or {}
        proof=_rejected_completed_submission(core,connection,frozen)
        if (row['state']!='running' or not frozen.get('send_admitted') or repair.get('admitted')
                or not proof or any(repair.get(k)!=v for k,v in proof.items())):
            raise ContractError('原提交纠正回执需要核对，不会重复执行。')
        repair['admitted']=True
        connection.execute('UPDATE workflow_runs SET snapshot_json=? WHERE id=?',
            (canonical(frozen).decode(),identifier))
        connection.execute("UPDATE employee_runs SET state='running',updated_at=? WHERE id=?",
            (utc_now(),frozen['employee_run_id']))
        core.repository.event('workflow_run:'+str(identifier),'workflow.result_correction_admitted',
            {'visit':frozen['pipeline_visit'],'message_id':proof['message_id']},connection=connection)
    prompt=('原回合已停止，正式提交被明确的结构校验拒绝，尚未形成交接回执。'
        '这是一回合提交格式纠正，不是重做原任务。先 read 核对原报告、receipt 和 result_schema，'
        '沿你已形成的专业判断，由你重新提交；不得重新采集、执行业务操作、改稿、派工或代做人工决定。'
        '若原判断不能确认，停止并如实说明；不要补造结论。'
        'result.status、result.summary 是外层字段，全部技能产出放在 result.output 中。'
        '沿原被拒绝的 operation_id='+proof['submission_id']+'。校验提示：'+proof['error']+
        '\n提交结构：'+json.dumps(result_schema(frozen['package'],frozen['pipeline_work']),ensure_ascii=False))
    status,reason=executor(frozen['work_chat_id'],prompt,core._cancel_event(identifier),
        'employee-work:'+str(identifier))
    return finish_turn(core,identifier,status,reason,expected_visit=frozen['pipeline_visit'])


def rearm_unstarted_correction(core,identifier):
    """Explicit recovery of a rejected preflight, never an admitted model turn.

    The original Handler persists the user message before starting the model.
    An unchanged, revalidated source message proves this correction never got
    that far. Any new message or unknown native effect keeps the fence closed.
    """
    with core.repository.connect()as connection:
        row=_row(connection,identifier);frozen=json.loads(row['snapshot_json'])
        repair=frozen.get('pipeline_result_correction')or{}
        if (row['state'] not in ('paused','needs_human','interrupted') or
                not repair.get('admitted') or (frozen.get('pipeline_execution')or{}).get('active')
                or frozen.get('pipeline_submission') or frozen.get('pipeline_applied_result')):return False
        proof=_rejected_completed_submission(core,connection,frozen)
        if not proof or any(repair.get(k)!=v for k,v in proof.items()):return False
        repair['admitted']=False;frozen.pop('pipeline_unresolved',None)
        _save(core,connection,row,frozen,'ready')
        core.repository.event('workflow_run:'+str(identifier),'workflow.correction_preflight_recovered',
            {'visit':frozen['pipeline_visit'],'message_id':proof['message_id']},connection=connection)
        return True


def _input_issue(definition,error,producer):
    fields=set(getattr(error,'fields',[]));assets=list(getattr(error,'assets',[]))
    declarations=[p for p in definition.get('parameters',[]) if p['key'] in fields]
    writers=sorted({w for p in declarations if p.get('source')=='employee' for w in p.get('writers',[])})
    user=bool(assets or any(p.get('source')=='user' for p in declarations))
    if not writers and not user:writers=[producer]
    return {'message':str(error),'fields':sorted(fields),'assets':assets,'responsible_positions':writers,'requires_user_input_or_authorization':user}


def _submission(core, connection, row, frozen, operation_id, result):
    try:
        if str(uuid.UUID(operation_id)) != operation_id:raise ValueError()
    except (ValueError, TypeError, AttributeError):
        raise ContractError('请使用原结果提交编号。') from None
    result = _result(frozen['package'], frozen['pipeline_work'], result)
    existing = frozen.get('pipeline_submission')
    request = {'operation_id': operation_id, 'result': result, 'visit': frozen['pipeline_visit']}
    event = connection.execute("SELECT data_json FROM events WHERE stream=? AND type='pipeline.result_submitted' LIMIT 1",
        ('source-pipeline-result:' + operation_id,)).fetchone()
    if event:
        saved = json.loads(event[0])
        if saved['request_sha256'] != digest({**request, 'workflow_id': row['id']}):
            raise ContractError('原结果编号已用于其他内容。')
        return saved['receipt']
    if existing:
        raise ContractError('本次岗位结果已经提交，请查询原回执。')
    definition = frozen['pipeline_work']['asset']['pipeline']; key = frozen['pipeline_work']['position_key']
    edge = None if result['output'].get('quality_feedback') else core._matching_edge(definition, key, result)
    if edge and edge['to'] in {p['key'] for p in definition['positions'] if p['kind'] == 'employee'}:
        bundle = control.read(core, frozen['pipeline_work']['reference'], connection)['bundle']
        role = bundle['roles'][edge['to']]
        # A returning visit invalidates its previous output and later consumers.
        prospective = copy.deepcopy(frozen)
        _lineage(connection, prospective, edge['to'], frozen.get('employee_run_id'), result)
        try:
            extra = {'id': frozen['employee_run_id'], 'position_key': key, 'state': result['status'], 'output_json': result}
            payload_for(core, connection, prospective, role, extra if frozen['employee_run_id'] in prospective['pipeline_lineage'] else None)
        except ContractError as error:
            issue=_input_issue(definition,error,key)
            owners='用户' if issue['requires_user_input_or_authorization'] else '、'.join(p['name'] for p in definition['positions'] if p['key'] in issue['responsible_positions'])
            raise ContractError('下游尚不能接收，请由'+owners+'补齐后再提交：' + str(error)) from error
    receipt = {'operation_id': operation_id, 'workflow_id': row['id'], 'visit': frozen['pipeline_visit'],
        'employee_run_id': frozen['employee_run_id']}
    from runteams_core.work.work_reports import catalog
    reports=[_report_ref(core,r) for r in catalog(core,workflow_id=row['id']) if r['binding'].get('employee_run_id')==frozen['employee_run_id']]
    frozen['pipeline_submission'] = {'result': result, 'receipt': receipt,'reports':reports}
    connection.execute('UPDATE workflow_runs SET snapshot_json=? WHERE id=?', (canonical(frozen).decode(), row['id']))
    core.repository.event('source-pipeline-result:' + operation_id, 'pipeline.result_submitted',
        {'request_sha256': digest({**request, 'workflow_id': row['id']}), 'receipt': receipt}, connection=connection)
    return receipt


def _lineage(connection, frozen, target, run_id=None, result=None):
    lineage = list(frozen.get('pipeline_lineage', []))
    if run_id and result and result['status'] == 'completed' and run_id not in lineage:
        lineage.append(run_id)
    for index, identifier in enumerate(lineage):
        row = connection.execute('SELECT position_key FROM employee_runs WHERE id=?', (identifier,)).fetchone()
        if row and row[0] == target:
            lineage = lineage[:index]
            break
    frozen['pipeline_lineage'] = lineage


def _move(core, connection, row, frozen, target, result, run_id=None):
    definition = frozen['pipeline_work']['asset']['pipeline']
    _lineage(connection, frozen, target, run_id, result)
    states = {s['key']: s['kind'] for s in definition.get('states', [])}
    if target in states:
        _save(core, connection, row, frozen, 'canceled' if states[target]=='dropped' else 'blocked' if states[target]=='pool' else 'completed', target)
        return
    position = next(p for p in definition['positions'] if p['key'] == target)
    if position['kind'] == 'approval':
        frozen['pipeline_waiting'] = {'kind':'approval','position_key': target, 'source_run_id': run_id}
        _save(core, connection, row, frozen, 'needs_approval', target)
        core.repository.event('workflow_run:' + str(row['id']), 'workflow.approval_requested',
            {'position_key': target, 'prompt': position.get('prompt') or '请确认是否继续'}, connection=connection)
        return
    bundle = control.read(core, frozen['pipeline_work']['reference'], connection)['bundle']; role = bundle['roles'][target]
    next_frozen = work.stage_snapshot(role['package'], role['context'], role['configuration'])
    next_frozen.update(pipeline_history=archive(frozen), pipeline_visit=frozen['pipeline_visit'] + 1,
        pipeline_generation=frozen['pipeline_generation'], pipeline_input=frozen['pipeline_input'],
        pipeline_lineage=frozen['pipeline_lineage'])
    if frozen.get('pipeline_execution'):next_frozen['pipeline_execution'] = frozen['pipeline_execution']
    next_frozen['pipeline_feedback'] = {'from': row['cursor_key'],
        'employee_run_id': run_id, 'summary': result['summary'], 'issues': result['issues'],
        'route': result['output'].get('route', '')}
    if frozen.get('pipeline_response') and target==row['cursor_key']:next_frozen['pipeline_response'] = frozen['pipeline_response']
    try:
        payload = payload_for(core, connection, next_frozen, role)
        state = 'ready'
    except ContractError as error:
        payload = copy.deepcopy(frozen['pipeline_input']);state = 'blocked'
        next_frozen['pipeline_handoff'] = {'to': target, 'from': row['cursor_key'],
            **_input_issue(definition,error,frozen['pipeline_work']['position_key'])}
        core.repository.event('workflow_run:' + str(row['id']), 'workflow.input_invalid', next_frozen['pipeline_handoff'], connection=connection)
    if control.read(core, frozen['pipeline_work']['reference'], connection)['status'] == 'paused':
        next_frozen['pipeline_pause'] = {'previous_state': state};state = 'paused'
    _save(core, connection, row, next_frozen, state, target, payload)


def finish_turn(core, identifier, status, reason='', *, expected_visit=None):
    with core.repository.connect() as connection:
        original=_row(connection,identifier);before=json.loads(original['snapshot_json'])
    if expected_visit is not None and before['pipeline_visit']!=expected_visit:return original['state']
    if not before.get('pipeline_applied_result') and before.get('work_chat_id'):
        from runteams_core.employees.employee_context import current as employee_context
        has_program=any(f['path']=='mcp/employee.mcpb' for b in employee_context().package_asset(before['package'])['skill_bundles'] for f in b['files'])
        if has_program:
            callback=getattr(core,'pipeline_program_control',None)
            try:
                if not callable(callback):raise ContractError('岗位程序宿主尚未就绪，不能确认交接。')
                callback('pause',[before['work_chat_id']])
            except Exception as error:
                message=str(error)[:1000]
                defer_settlement(core,identifier,before['pipeline_visit'],error)
                raise RecoveryPending('岗位程序尚未确认停止，交接保留原回执：'+message) from error
    with core.repository.connect() as connection:
        row = _row(connection, identifier); frozen = json.loads(row['snapshot_json'])
        if frozen['pipeline_visit']!=before['pipeline_visit']:return row['state']
        if row['state'] == 'canceled' or frozen.get('pipeline_applied_result'):
            return row['state']
        frozen.pop('pipeline_recovery_pending',None);frozen.pop('pipeline_program_error',None)
        submitted = frozen.get('pipeline_submission')
        if frozen.get('pipeline_result_invalidated'):
            submitted=None;reason=frozen['pipeline_result_invalidated']
        result = submitted['result'] if submitted else None
        if (not result and status in ('completed','interrupted')
                and _queue_result_correction(core,connection,row,frozen)):
            return connection.execute('SELECT state FROM workflow_runs WHERE id=?',(identifier,)).fetchone()[0]
        if result:
            _result(frozen['package'], frozen['pipeline_work'], result)
            state = result['status'];frozen['pipeline_applied_result'] = True
        else:
            state = {'completed': 'needs_human', 'blocked': 'needs_human', 'failed': 'failed',
                'cancelled': 'canceled', 'canceled': 'canceled'}.get(status, 'interrupted')
            reason = reason or ('岗位尚未提交可验收结果，不会将对话结束当作交接完成。' if status == 'completed' else '原工作结果需要核对，不会自动重发。')
            result = {'status': state, 'summary': '', 'output': {}, 'issues': [reason], 'artifacts': []}
            if frozen.get('send_admitted'):frozen['pipeline_unresolved'] = True
        if frozen.get('employee_run_id'):
            connection.execute('UPDATE employee_runs SET state=?,output_json=?,updated_at=? WHERE id=?',
                (state, canonical({**result, 'transport_status': status,'report_references':(submitted or {}).get('reports',[])}).decode(), utc_now(), frozen['employee_run_id']))
        definition = frozen['pipeline_work']['asset']['pipeline']; key = frozen['pipeline_work']['position_key']
        edge = core._matching_edge(definition, key, result) if submitted and not result['output'].get('quality_feedback') else None
        if edge:
            core._route_workflow(identifier,edge,frozen['employee_run_id'])
            _move(core, connection, row, frozen, edge['to'], result, frozen['employee_run_id'])
        else:
            if submitted and state == 'completed':state = 'blocked';reason = '岗位已提交结果，但没有匹配的流转连线；请核对流水线定义。'
            if submitted and state not in control.TERMINAL:
                frozen['pipeline_waiting']={'kind':'result','position_key':key,'state':state,
                    'source_run_id':frozen.get('employee_run_id'),'result':result}
            if control.read(core, frozen['pipeline_work']['reference'], connection)['status'] == 'paused' and state not in control.TERMINAL:
                frozen['pipeline_pause'] = {'previous_state': state};state = 'paused'
            _save(core, connection, row, frozen, state)
            core.repository.event('workflow_run:' + str(identifier), 'workflow.' + state,
                {'reason': reason, 'position_key': key}, connection=connection)
        return connection.execute('SELECT state FROM workflow_runs WHERE id=?', (identifier,)).fetchone()[0]


def invalidate_result(core,identifier,visit,reason):
    with core.repository.connect() as connection:
        row=_row(connection,identifier);frozen=json.loads(row['snapshot_json'])
        if frozen['pipeline_visit']!=visit:raise ContractError('岗位已经流转，不能更改旧结果。')
        frozen['pipeline_result_invalidated']=reason
        connection.execute('UPDATE workflow_runs SET snapshot_json=? WHERE id=?',(canonical(frozen).decode(),identifier))
        core.repository.event('workflow_run:'+str(identifier),'workflow.input_changed',{'position_key':row['cursor_key'],'reason':reason},connection=connection)


def recover(core, identifier):
    core.repository.storage.assert_executable(identifier)
    with core.repository.connect() as connection:
        row = _row(connection, identifier); frozen = json.loads(row['snapshot_json'])
    if row['state'] not in control.TERMINAL:
        if frozen.get('pipeline_submission') and not frozen.get('pipeline_applied_result'):
            finish_turn(core, identifier, 'interrupted', '沿原结果回执恢复，未重新发送。',expected_visit=frozen['pipeline_visit'])
        elif frozen.get('send_admitted') and not frozen.get('pipeline_applied_result'):
            finish_turn(core, identifier, 'interrupted', '原工作结果需要核对，不会自动重发。')
        elif row['state'] in ('running','interrupted') and not frozen.get('send_admitted'):
            with core.repository.connect() as connection:
                row=_row(connection,identifier);frozen=json.loads(row['snapshot_json'])
                paused=control.read(core,frozen['pipeline_work']['reference'],connection)['status']=='paused'
                if paused:frozen['pipeline_pause']={'previous_state':'ready'}
                _save(core,connection,row,frozen,'paused' if paused else 'ready')
    control.end_execution(core, identifier,(frozen.get('pipeline_execution') or {}).get('token'))
    core.__dict__.get('_pending_pipeline_recoveries',set()).discard(identifier)
    return True


def employee_call(arguments, context):
    from runteams_core.storage import device_data
    from runteams_core.storage import product_store
    from runteams_core.work.device_work_services import current as device_work_service
    if not isinstance(arguments, dict) or set(arguments) - set(INPUT_SCHEMA['properties']):raise ContractError('岗位交接参数无效。')
    scope = device_data.identity()
    from runteams_core.foundation.identity.work_identity import principal
    if context.get('actor_id') != principal(scope) or not device_data.personal():raise PermissionError('原岗位身份未能确认。')
    cid = context.get('chat_id');control.check_chat_operation(cid)
    session = product_store.get_chat(cid, include_messages=False)
    if not (session or {}).get('context', {}).get('pipeline_work'):raise PermissionError('此工具仅用于流水线当前岗位。')
    identifier = session['context']['employee_work']['workflow_id'];core = device_work_service()
    with core.repository.audit_context(actor_id=principal(scope), source='agent_tool'),core.repository.connect() as connection:
        row = _row(connection, identifier);frozen = json.loads(row['snapshot_json'])
        if frozen.get('work_chat_id') != cid or row['state'] != 'running' or not (frozen.get('pipeline_execution') or {}).get('active'):
            raise PermissionError('当前岗位已经交接或停止。')
        operation = arguments.get('operation')
        if operation == 'submit' and set(arguments) == {'operation', 'operation_id', 'result'}:
            if len(canonical(arguments)) > 96 * 1024:raise ContractError('岗位结果过大，请使用正式记录引用。')
            return _submission(core, connection, row, frozen, arguments['operation_id'], arguments['result'])
        from runteams_core.work.work_reports import _agent_document
        reports = _reports(core,connection,frozen)
        if operation == 'read_report' and set(arguments) == {'operation', 'report_id'}:
            if type(arguments['report_id']) is not int or not any(r['id'] == arguments['report_id'] for r in reports):raise PermissionError('这份汇报不属于当前获准交接的工作。')
            reference=next(r for r in reports if r['id']==arguments['report_id'])
            document=core.historical_document_detail(reference['artifact_id'])
            if not document or document['revision']!=reference['revision'] or hashlib.sha256(document['content'].encode()).hexdigest()!=reference['sha256']:
                raise ContractError('原交接汇报版本无法确认，请核对原记录。')
            return {'document': _agent_document(document), 'read_only': True}
        if operation != 'read' or set(arguments) != {'operation'}:raise ContractError('请选择读取交接、读取汇报或提交结果。')
        role = {'context': frozen['pipeline_work'], 'package': frozen['package']}
        payload = payload_for(core, connection, frozen, role)
        return {'position_key': frozen['pipeline_work']['position_key'], 'parameters': payload['parameters'],
            'stage': payload['context']['pipeline_stage'], 'reports': reports,
            'output_schema': (declared(frozen['package'], payload['skill_key']) or {}).get('output_schema', {'type': 'object'}),
            'result_schema': result_schema(frozen['package'],frozen['pipeline_work']),
            'receipt': (frozen.get('pipeline_submission') or {}).get('receipt')}


def _command_request(data):
    fields={'operation_id','reference','workflow_id','expected_visit','action'}
    if not isinstance(data,dict) or data.get('action') not in ('decide','respond','recover','input'):
        raise ContractError('请选择处理人工决定、回答问题或核对原工作。')
    extra={'decide':{'decision','note'},'respond':{'response'},'recover':set(),'input':{'parameters'}}[data['action']]
    if set(data)!=fields|extra:raise ContractError('工作恢复参数无效。')
    try:
        if str(uuid.UUID(data['operation_id']))!=data['operation_id']:raise ValueError()
    except (ValueError,TypeError,AttributeError):raise ContractError('请沿原工作操作编号恢复。') from None
    if type(data['workflow_id']) is not int or type(data['expected_visit']) is not int or min(data['workflow_id'],data['expected_visit'])<1:
        raise ContractError('原工作或岗位访问编号无效。')
    if data['action']=='input':
        if not isinstance(data['parameters'],dict) or len(canonical(data['parameters']))>65536:raise ContractError('任务输入格式无效。')
    for key in extra-{'parameters'}:
        if not isinstance(data[key],str) or len(data[key])>4000 or key!='note' and not data[key].strip():
            raise ContractError('请填写有效的决定或回答。')
    return {**copy.deepcopy(data),'reference':pipeline_references.checked_reference(data['reference'])}


def _prepared_recovery(core,request,active_ids,read_only):
    if read_only or request['action']!='recover':return None
    with core.repository.connect() as connection:
        if connection.execute("SELECT 1 FROM events WHERE stream=? AND type='pipeline.flow_committed'",
                ('source-pipeline-flow:'+request['operation_id'],)).fetchone():return None
        row=_row(connection,request['workflow_id']);frozen=json.loads(row['snapshot_json'])
        if not frozen.get('pipeline_setup_required'):return None
        if (frozen['pipeline_work']['reference']!=request['reference'] or frozen['pipeline_visit']!=request['expected_visit']):
            raise ContractError('岗位已改变，请从原工作记录核对准备现场。')
        if (row['state'] not in ('blocked','needs_human') or request['workflow_id'] in active_ids
                or (frozen.get('pipeline_execution') or {}).get('active')
                or control.read(core,request['reference'],connection)['status']!='running'):
            raise ContractError('原岗位尚未停止或流水线已暂停，请先核对运行状态。')
        core.repository.storage.assert_executable(request['workflow_id'])
    from runteams_core.employees.employee_work_contracts import verify_frozen, verify_prepared_session
    from runteams_core.employees.employee_context import current as employee_context
    from runteams_core.storage import device_data
    verify_frozen(frozen,device_data.identity())
    from runteams_core.storage import product_store
    verify_prepared_session(frozen,product_store.get_chat(frozen['work_chat_id'],include_messages=False),request['workflow_id'],row['task_id'])
    # Read readiness outside the work transaction. This neither grants a
    # service nor sends a model turn; execution rechecks before admission.
    employee_context().prepare_work(core,frozen['work_chat_id'],frozen)
    callback=getattr(core,'pipeline_program_control',None)
    if callable(callback):callback('start',[frozen['work_chat_id']])
    return digest(frozen)


def command(core,data,active_ids=(),*,read_only=False):
    core._actor();request=_command_request(data);identifier=request['workflow_id'];key=request['operation_id']
    prepared=_prepared_recovery(core,request,active_ids,read_only)
    with core.repository.connect() as connection:
        row=_row(connection,identifier);frozen=json.loads(row['snapshot_json'])
        if (frozen.get('pipeline_work') or {}).get('reference')!=request['reference']:raise PermissionError('工作不属于这条流水线。')
        event=connection.execute("SELECT data_json FROM events WHERE stream=? AND type='pipeline.flow_committed' LIMIT 1",('source-pipeline-flow:'+key,)).fetchone()
        if event:
            value=json.loads(event[0])
            if value['request_sha256']!=digest(request):raise ContractError('原操作编号已用于其他内容。')
            receipt=value['receipt']
        elif read_only:
            return {'operation_id':key,'status':'unknown'}
        else:
            core.repository.storage.assert_executable(identifier)
            if frozen['pipeline_visit']!=request['expected_visit']:raise ContractError('岗位已流转或更新，请核对当前工作。')
            if identifier in active_ids:raise ContractError('原岗位仍在执行，请等待收尾，不会并发恢复。')
            saved=control.read(core,request['reference'],connection)
            if (frozen.get('pipeline_execution') or {}).get('active'):
                raise ContractError('原执行尚未确认停止，请等待系统核对，不会并发恢复。')
            if request['action']!='recover' and saved['status']!='running':
                raise ContractError('流水线已暂停或原岗位尚未收尾。')
            waiting=frozen.get('pipeline_waiting') or {};action=request['action']
            if action=='recover' and row['state']=='running':raise ContractError('原工作仍在执行，请等待执行器确认停止。')
            if action=='decide':
                if row['state']!='needs_approval' or waiting.get('kind')!='approval':raise ContractError('当前工作没有待处理的人工决定。')
                decision=request['decision'].strip()
                result={'status':'completed','summary':request['note'],'output':{'route':decision},'issues':[],'artifacts':[]}
                edge=core._matching_edge(saved['bundle']['asset']['pipeline'],row['cursor_key'],{'status':decision,'output':{'route':decision}})
                if not edge:raise ContractError('该决定没有配置流转连线，请先核对流水线。')
                core.repository.event('workflow_run:'+str(identifier),'workflow.approval_decided',
                    {'position_key':row['cursor_key'],'decision':decision,'note':request['note']},connection=connection)
                frozen.pop('pipeline_waiting',None)
                core._route_workflow(identifier,edge,waiting.get('source_run_id'))
                _move(core,connection,row,frozen,edge['to'],result,waiting.get('source_run_id'))
            elif action=='respond':
                if row['state'] not in ('blocked','needs_human') or waiting.get('kind')!='result' or waiting['result']['status'] not in ('blocked','needs_human'):
                    raise ContractError('只有已确认的问题等待才能接续回答；未知发送不能重发。')
                frozen['pipeline_response']=request['response'].strip();frozen.pop('pipeline_waiting',None)
                _move(core,connection,row,frozen,row['cursor_key'],waiting['result'],waiting.get('source_run_id'))
                core.repository.event('workflow_run:'+str(identifier),'workflow.human_responded',{'position_key':row['cursor_key']},connection=connection)
            elif action=='input':
                issue=frozen.get('pipeline_handoff') or {}
                if row['state']!='blocked' or not issue.get('requires_user_input_or_authorization') or frozen.get('send_admitted'):
                    raise ContractError('当前工作没有可补齐的已确认任务输入；未知发送不能重发。')
                allowed={p['key'] for p in frozen['pipeline_work']['asset']['pipeline'].get('parameters',[]) if p.get('source')=='user' and (not p.get('visible_to') or row['cursor_key'] in p['visible_to'])}
                if not request['parameters'] or set(request['parameters'])-allowed:
                    raise ContractError('只能补齐已声明的用户任务输入，不能改写员工产出或资料授权。')
                frozen['pipeline_input']['parameters']={**frozen['pipeline_input'].get('parameters',{}),**copy.deepcopy(request['parameters'])}
                role=saved['bundle']['roles'][row['cursor_key']]
                payload_for(core,connection,frozen,role)
                _move(core,connection,row,frozen,row['cursor_key'],{'status':'completed','summary':'使用者补齐了任务输入。','output':{},'issues':[]})
                core.repository.event('workflow_run:'+str(identifier),'workflow.input_supplied',{'position_key':row['cursor_key'],'fields':sorted(request['parameters'])},connection=connection)
            else:
                if row['state'] in control.TERMINAL:raise ContractError('已结束的工作不重新运行。')
                if prepared:
                    if digest(frozen)!=prepared:raise ContractError('岗位准备现场已变化，请重新核对。')
                    frozen.pop('pipeline_setup_required')
                    _save(core,connection,row,frozen,'ready')
                    core.repository.event('workflow_run:'+str(identifier),'workflow.preparation_completed',
                        {'visit':frozen['pipeline_visit'],'chat_id':frozen['work_chat_id']},connection=connection)
                # Admit this recovery request durably. Program stop callbacks
                # and receipt settlement run AFTER the transaction, like pause.
                # A duplicate request can settle only its original visit.
            receipt={'operation_id':key,'workflow_id':identifier,'visit':request['expected_visit'],'action':action}
            core.repository.event('source-pipeline-flow:'+key,'pipeline.flow_committed',{'request_sha256':digest(request),'receipt':receipt},connection=connection)
    if not read_only:
        if request['action']=='recover':
            with core.repository.connect() as connection:
                latest=_row(connection,identifier);current=json.loads(latest['snapshot_json'])
            if (current['pipeline_visit']==request['expected_visit'] and latest['state'] not in ('ready','running',*control.TERMINAL)
                    and not (current.get('pipeline_execution') or {}).get('active') and current.get('send_admitted')
                    and not current.get('pipeline_applied_result')):
                finish_turn(core,identifier,'interrupted','沿原结果回执核对，不会重新发送。',expected_visit=request['expected_visit'])
                if not rearm_unstarted_correction(core,identifier):
                    from runteams_core.pipelines.pipeline_context import current as pipeline_context
                    pipeline_context().reconcile_result(core,identifier)
        control.settle_pause(core,request['reference'])
    try:return {'operation_id':key,'status':'committed','receipt':receipt,'result':work.work(core,request['reference'],identifier)}
    except PermissionError:raise
    except Exception as error:raise work.WorkAdmissionUnknown(key) from error
