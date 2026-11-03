"""Local pause/apply/start for source pipelines, using the existing work ledger.

Commands, applied employee/configuration snapshots and receipts share the normal
event transaction. A pause drains admitted turns; it never kills an independent
employee or replays an uncertain external effect.
"""
from . import pipeline_references
import copy
import json
import time
import uuid
from contextlib import nullcontext

from . import source_pipeline_work as work
from . import workflow_policy
from .contracts import ContractError
from .creator_contracts import canonical, digest
from .repository import utc_now

TERMINAL = ('completed', 'failed', 'canceled')
STATE_EVENT = 'pipeline.runtime_state'


def stream(ref):
    ref = pipeline_references.checked_reference(ref)
    return 'source-pipeline-runtime:' + ref['source_id'] + ':' + ref['pipeline_source']


def read(core, ref, connection=None):
    ref = pipeline_references.checked_reference(ref)
    if connection is None:
        with core.repository.connect() as connection:
            return read(core, ref, connection)
    row = connection.execute('SELECT data_json FROM events WHERE stream=? AND type=? ORDER BY id DESC LIMIT 1',
        (stream(ref), STATE_EVENT)).fetchone()
    if row:
        value=json.loads(row[0])
        if not isinstance(value,dict) or value.get('reference')!=ref:
            raise ContractError('流水线运行记录的资产归属不一致。')
        return value
    return {'reference': ref, 'revision': 0, 'status': 'running', 'bundle': None, 'quiesced_revision': None}


def _write(core, connection, state):
    core.repository.event(stream(state['reference']), STATE_EVENT, state, connection=connection)


def _rows(connection, ref):
    return connection.execute("SELECT w.*,t.payload_json,t.trashed_at FROM workflow_runs w JOIN tasks t ON t.id=w.task_id "
        "WHERE json_extract(w.snapshot_json,'$.pipeline_work.reference.source_id')=? "
        "AND json_extract(w.snapshot_json,'$.pipeline_work.reference.pipeline_source')=? ORDER BY w.id",
        (ref['source_id'], ref['pipeline_source'])).fetchall()


def _live(rows, active_ids=()):
    active_ids = set(active_ids)
    return [row['id'] for row in rows if row['state'] == 'running' or row['id'] in active_ids or
        (json.loads(row['snapshot_json']).get('pipeline_execution') or {}).get('active')]


def _owned_entry(ref):
    from .creator_contracts import strict_json
    revisions=work.source(ref)
    with revisions.locked():
        files=revisions._files(revisions._head());project=strict_json(files['project.json'])
    if ref['pipeline_source'] not in project['entrypoints'].get('pipelines',[]) or ref['pipeline_source'] not in files:
        raise ContractError('流水线不属于当前源码工程。')


def state(core, ref, active_ids=()):
    core._actor(); ref = pipeline_references.checked_reference(ref)
    with core.repository.connect() as connection:
        saved = read(core, ref, connection); rows = _rows(connection, ref)
    if saved['revision']==0:_owned_entry(ref)
    live = _live(rows, active_ids)
    status = saved['status']
    if status == 'paused' and (live or saved['quiesced_revision'] != saved['revision']):
        status = 'pausing'
    bundle = saved['bundle']; positions = []
    if bundle:
        for position in bundle['asset']['pipeline']['positions']:
            role = bundle['roles'].get(position['key'])
            positions.append({'key': position['key'], 'kind': position['kind'], 'name': position['name'],
                **({'employee_reference': role['package']['reference'], 'revision': role['package']['revision'],
                    'configuration_revision': (role['configuration'] or {}).get('revision')} if role else {})})
    return {'reference': ref, 'revision': saved['revision'], 'status': status,
        'applied_revision': bundle['revision'] if bundle else None,
        'generation': bundle['generation'] if bundle else 0, 'positions': positions,
        'active_workflow_ids': live, 'workflows': [{'id': r['id'], 'state': r['state'],
            'position_key':r['cursor_key'],'settlement_pending':bool(json.loads(r['snapshot_json']).get('pipeline_recovery_pending')),
            'generation': json.loads(r['snapshot_json']).get('pipeline_generation'),
            'requires_reconciliation': bool(json.loads(r['snapshot_json']).get('pipeline_unresolved'))}
            for r in rows if r['state'] not in TERMINAL and not r['trashed_at']],
        'pause_error': saved.get('pause_error', ''), 'storage_scope': 'device'}


def _role(package, context):
    from .employee_context import current as employee_context
    from .pipeline_context import current as pipeline_context
    employee_context().validate_package(package)
    employee = employee_context().package_asset(package)
    return {'package': package, 'context': context,
        'configuration': pipeline_context().member_configuration(context['reference'], package).snapshot() if employee['employee'].get('configuration') else None}


def admission_candidate(core, context, package):
    current = read(core, context['reference'])
    if current['status'] != 'running':
        raise ContractError('流水线已暂停，不能开始新工作。')
    if current['bundle']:
        if current['bundle']['revision'] != context.get('source_revision', package['revision']):
            raise ContractError('流水线源码已有更新，请先暂停、应用更新后启动；不会混用版本。')
        return current['bundle']
    bundle=prepare_bundle(context['reference'], package['build_operation_key'], context.get('source_revision', package['revision']))
    bundle['generation']=1
    return bundle


def dispatch_contract(core, ref,start_column_key=None):
    """New work follows the applied snapshot, even while the author edits a draft."""
    core._actor(); ref = pipeline_references.checked_reference(ref)
    saved = read(core, ref)
    if not saved['bundle']:
        return work.describe(ref,start_column_key)
    bundle = saved['bundle']; position, member = work._selection(bundle['asset'],start_column_key)
    role = bundle['roles'][position['key']]
    from .employee_context import current as employee_context
    from .creator_conversation_assets import extension
    employee_context().validate_package(role['package']); work.verify_context(role['context'], role['package'], read_build=True)
    employee = employee_context().package_asset(role['package'])
    skill = next(b for b in employee['skill_bundles'] if b['package_key'] == position['skill_key'])
    declared = extension(skill).get('work')
    entry=next(p for p in bundle['asset']['pipeline']['positions'] if p['key']==(start_column_key or workflow_policy.start_position(bundle['asset']['pipeline'])))
    return {'reference': ref, 'revision': bundle['revision'], 'name': bundle['asset']['pipeline']['name'],
        'position_key': entry['key'], 'position_name': entry['name'],'kind':entry['kind'],
        'employee_source': member.get('source', member['ref']), 'employee_name': employee['employee']['name'] if entry['kind']=='employee' else None,
        'skill_key': position['skill_key'],
        'assets':copy.deepcopy(declared.get('assets',[])) if declared else [],
        'input_schema': copy.deepcopy(declared['input_schema']) if declared and entry['kind']=='employee' else {'type': 'object'}}


def admit(connection, core, ref, candidate,start_column_key=None):
    current = read(core, ref, connection)
    if current['status'] != 'running':
        raise ContractError('流水线已暂停，不能开始新工作。')
    if current['bundle'] is None:
        current.update(bundle=candidate, revision=current['revision'] + 1)
        _write(core, connection, current)
    bundle = current['bundle']
    if bundle['revision'] != candidate['revision'] or bundle['generation']!=candidate['generation']:
        raise ContractError('流水线运行版本已变化，请核对原工作。')
    position, _ = work._selection(bundle['asset'],start_column_key)
    return bundle['roles'][position['key']], bundle['generation']


def prepare_bundle(ref, operation_id, revision):
    from .creator_source_import import validate_source
    revisions = work.source(ref)
    with revisions.locked():
        if revisions._head() != revision:
            raise ContractError('流水线源码已有更新，请重新核对要应用的版本。')
        files = revisions._files(revision)
    compiled = validate_source(files)
    asset = compiled['pipelines'].get(ref['pipeline_source'])
    if asset is None:
        raise ContractError('流水线源码入口已不存在。')
    from .pipeline_dependency_contracts import key as member_key, selector
    has_dependencies = any('dependency' in member for member in asset['employees'])
    if has_dependencies:
        from .employee_context import current as employee_context
        deadline = time.monotonic() + 200
        while True:
            try:
                employee_context().prepare_source_build(revisions.store, ref['source_id'], revision, operation_id)
                break
            except BlockingIOError:
                if time.monotonic() >= deadline: raise ContractError('流水线运行包正在准备，请沿原操作核对。') from None
                time.sleep(.05)
    roles = {}; packages = {}; configurations={}
    for position in asset['pipeline']['positions']:
        if position['kind'] != 'employee':
            continue
        member = next(row for row in asset['employees'] if row['ref'] == position['employee_ref'])
        employee_key = member_key(member)
        if employee_key not in packages:
            packages[employee_key] = work.prepare_member(ref, selector(member), operation_id, revision)
        package = packages[employee_key]
        context = work._context(ref, package, position['key'], revision if has_dependencies else None)
        if employee_key not in configurations:
            configurations[employee_key] = _role(package, context)['configuration']
        roles[position['key']] = {'package': package, 'context': context, 'configuration': copy.deepcopy(configurations[employee_key])}
    if not roles:
        raise ContractError('流水线至少需要一个员工岗位。')
    canonical_asset = next(iter(roles.values()))['context']['asset']
    bundle = {'revision': revision, 'generation': 0, 'asset': canonical_asset, 'roles': roles}
    if 'configuration' in canonical_asset:
        from .pipeline_context import current as pipeline_context
        bundle['configuration'] = pipeline_context().own_configuration(ref, canonical_asset, revision).snapshot()
    return bundle


def _park(core, connection, row):
    if row['state'] in TERMINAL or row['state'] in ('paused', 'running'):
        return
    frozen = json.loads(row['snapshot_json'])
    frozen['pipeline_pause'] = {'previous_state': row['state']}
    connection.execute("UPDATE workflow_runs SET state='paused',snapshot_json=?,updated_at=? WHERE id=?",
        (canonical(frozen).decode(), utc_now(), row['id']))
    connection.execute("UPDATE tasks SET state='paused',updated_at=? WHERE id=?", (utc_now(), row['task_id']))
    core.repository.event('workflow_run:' + str(row['id']), 'workflow.paused', {'previous_state': row['state']}, connection=connection)


def _program_chats(rows):
    chats = set(); has_program = False
    from .employee_context import current as employee_context
    for row in rows:
        frozen = json.loads(row['snapshot_json'])
        versions = [frozen] + [item['snapshot'] for item in frozen.get('pipeline_history', [])]
        for version in versions:
            cid = version.get('work_chat_id')
            if not cid:
                continue
            chats.add(cid)
            has_program |= any(f['path'] == 'mcp/employee.mcpb' for b in employee_context().package_asset(version['package'])['skill_bundles'] for f in b['files'])
    return sorted(chats), has_program


def own_program_chats(ref):
    from . import device_data
    ref = pipeline_references.checked_reference(ref)
    with device_data.connect(readonly=True) as connection:
        rows = connection.execute("SELECT id,context_json FROM chats WHERE kind='general' AND subject_type='workspace' "
            "AND json_extract(context_json,'$.source_pipeline_workspace.source_id')=? "
            "AND json_extract(context_json,'$.source_pipeline_workspace.pipeline_source')=?",
            (ref['source_id'], ref['pipeline_source'])).fetchall()
    return [row['id'] for row in rows if json.loads(row['context_json']).get('source_pipeline_workspace') == ref]


def settle_pause(core, ref):
    with core.repository.connect() as connection:
        current = read(core, ref, connection); rows = _rows(connection, ref)
    if current['status'] != 'paused' or current['quiesced_revision'] == current['revision'] or _live(rows):
        return
    try:
        chats, has_program = _program_chats(rows)
        own_chats = own_program_chats(ref)
        chats = sorted(set(chats) | set(own_chats))
        has_program |= bool(own_chats and current.get('bundle') and current['bundle']['asset'].get('programs'))
        callback = getattr(core, 'pipeline_program_control', None)
        if has_program and not callable(callback):
            raise ContractError('员工程序宿主尚未就绪，不能确认已安全暂停。')
        if callable(callback):
            callback('pause', chats)
        error = ''
    except Exception as failure:
        error = str(failure)[:1000]
    with core.repository.connect() as connection:
        saved = read(core, ref, connection)
        if saved['status'] != 'paused' or saved['revision'] != current['revision'] or _live(_rows(connection, ref)):
            return
        saved['pause_error'] = error
        if not error:
            saved['quiesced_revision'] = saved['revision']
        _write(core, connection, saved)


def _request(data):
    if not isinstance(data, dict) or set(data) not in (
            {'operation_id', 'reference', 'action', 'expected_revision'},
            {'operation_id', 'reference', 'action', 'expected_revision', 'source_revision'}):
        raise ContractError('流水线控制参数无效。')
    try:
        key = str(uuid.UUID(data['operation_id']))
    except (ValueError, TypeError, AttributeError):
        raise ContractError('原操作编号无效。') from None
    if key != data['operation_id'] or type(data['expected_revision']) is not int or data['expected_revision'] < 0:
        raise ContractError('原操作编号或运行版本无效。')
    if data['action'] not in ('pause', 'update', 'start') or (data['action'] == 'update') != ('source_revision' in data):
        raise ContractError('请选择暂停、应用更新或启动；更新必须指定已保存源码版本。')
    return key, {**copy.deepcopy({k: v for k, v in data.items() if k != 'operation_id'}),
        'reference': pipeline_references.checked_reference(data['reference'])}


def _receipt(connection, key, request):
    row = connection.execute("SELECT data_json FROM events WHERE stream=? AND type='pipeline.control_committed' ORDER BY id DESC LIMIT 1",
        ('source-pipeline-control:' + key,)).fetchone()
    if row is None:
        return None
    value = json.loads(row[0])
    if value['request_sha256'] != digest(request):
        raise ContractError('原操作编号已用于其他控制内容。')
    return value['receipt']


def control_operation(core, data, active_ids=()):
    core._actor(); key, request = _request(data)
    with core.repository.connect() as connection:
        receipt = _receipt(connection, key, request)
    return {'operation_id': key, 'status': 'committed' if receipt else 'unknown',
        **({'receipt': receipt, 'state': state(core, request['reference'], active_ids)} if receipt else {})}


def _project(core, data, active_ids):
    try:
        return control_operation(core, data, active_ids)
    except PermissionError:
        raise
    except Exception as error:
        raise work.WorkAdmissionUnknown(data['operation_id']) from error


def _updated(core, row, bundle):
    previous = json.loads(row['snapshot_json']); key = previous['pipeline_work']['position_key']
    role = bundle['roles'].get(key)
    if role is None:
        raise ContractError('工作 {} 的原岗位 {} 已删除或改为人工决定。'.format(row['id'], key))
    frozen = work.stage_snapshot(role['package'], role['context'], role['configuration'])
    from .source_pipeline_flow import archive
    frozen.update(pipeline_visit=previous['pipeline_visit']+1,
        **{k:copy.deepcopy(previous[k]) for k in ('pipeline_input','pipeline_lineage','pipeline_feedback','pipeline_response','pipeline_waiting') if k in previous})
    waiting=previous.get('pipeline_waiting') or {}
    if waiting.get('kind')=='approval' and not any(p['key']==waiting['position_key'] and p['kind']=='approval' for p in bundle['asset']['pipeline']['positions']):
        raise ContractError('工作 {} 正在等待的人工决定岗位已删除或变更。'.format(row['id']))
    try:
        from .source_pipeline_flow import payload_for
        with core.repository.connect() as connection:
            payload=json.loads(row['payload_json']) if waiting.get('kind')=='approval' else payload_for(core,connection,frozen,role)
    except ContractError as error:
        raise ContractError('工作 {} 不符合更新后的岗位输入：{}'.format(row['id'], error)) from error
    frozen['pipeline_history'] = archive(previous)
    frozen['pipeline_generation'] = bundle['generation']
    frozen['source'] = previous['source']
    unresolved = bool(previous.get('send_admitted') and not previous.get('pipeline_applied_result') or previous.get('pipeline_unresolved'))
    if unresolved:
        frozen['pipeline_unresolved'] = True
    prior = (previous.get('pipeline_pause') or {}).get('previous_state', row['state'])
    frozen['pipeline_pause'] = {'previous_state': prior if unresolved and prior not in ('paused', 'running', 'ready') else
        'interrupted' if unresolved else 'ready'}
    return frozen, payload


def command(core, data, active_ids=()):
    core._actor(); key, request = _request(data); ref = request['reference']; action = request['action']
    with core.repository.connect() as connection:
        receipt = _receipt(connection, key, request)
    if receipt:
        if action == 'pause': settle_pause(core, ref)
        return _project(core, data, active_ids)
    if action=='pause' and read(core,ref)['revision']==0:
        _owned_entry(ref)
    candidate = None; validated_bundle = None
    if action in ('update', 'start'):
        settle_pause(core, ref)
        current = state(core, ref, active_ids)
        if current['status'] != 'paused' or current['revision'] != request['expected_revision']:
            with core.repository.connect() as connection:committed=_receipt(connection,key,request)
            if committed:return _project(core,data,active_ids)
            if current['status'] != 'paused':
                raise ContractError('请先暂停流水线，并等待岗位执行确实结束后再更新或启动。')
            raise ContractError('流水线运行状态已变化，请重新核对。')
        if action == 'update':
            candidate = prepare_bundle(ref, key, request['source_revision'])
        else:
            saved=read(core,ref);bundle=saved['bundle']
            if not bundle:raise ContractError('请先应用当前保存的流水线更新，再启动。')
            work._selection(bundle['asset'])
            from .employee_context import current as employee_context

            for role in bundle['roles'].values():
                employee_context().validate_package(role['package']);work.verify_context(role['context'],role['package'],read_build=True)
                if role['configuration'] is not None:employee_context().validate_package_configuration(role['package'],role['configuration'])
            if 'configuration' in bundle:

                employee_context().validate_configuration_snapshot(bundle['asset']['configuration'], ref, bundle['revision'], bundle['configuration'])
            validated_bundle=digest(bundle)
            with core.repository.connect() as connection:rows=_rows(connection,ref)
            ready_chats=[f['work_chat_id'] for r in rows if r['state']=='paused'
                for f in [json.loads(r['snapshot_json'])] if f.get('work_chat_id') and
                not f.get('pipeline_unresolved') and not f.get('send_admitted')]
            callback=getattr(core,'pipeline_program_control',None)
            if callable(callback):callback('start',sorted(set(ready_chats) | set(own_program_chats(ref))))
    revisions = work.source(ref) if action == 'update' else None
    # The existing employee runner may read an immutable source while holding
    # the work transaction. Use the same order so updating a different pipeline
    # cannot deadlock an independent employee preparing its work conversation.
    with core.repository.connect() as connection, (revisions.locked() if revisions else nullcontext()):
        connection.execute('BEGIN IMMEDIATE')
        receipt = _receipt(connection, key, request)
        if receipt is None:
            saved = read(core, ref, connection); rows = _rows(connection, ref)
            if saved['revision'] != request['expected_revision']:
                raise ContractError('流水线运行状态已变化，请重新核对。')
            if action == 'pause':
                saved.update(status='paused', revision=saved['revision'] + 1, quiesced_revision=None, pause_error='')
                for row in rows: _park(core, connection, row)
            else:
                if (saved['status'] != 'paused' or saved['quiesced_revision'] != saved['revision'] or _live(rows, active_ids)):
                    raise ContractError('岗位执行尚未确认停止，流水线继续保持暂停。')
                if action == 'update':
                    if revisions._head() != candidate['revision']:
                        raise ContractError('源码在准备期间已有更新，请核对原版本。')
                    candidate['generation'] = (saved['bundle']['generation'] if saved['bundle'] else 0) + 1
                    changes = [(r, *_updated(core, r, candidate)) for r in rows if r['state'] not in TERMINAL and not r['trashed_at']]
                    for row, frozen, payload in changes:
                        connection.execute('UPDATE workflow_runs SET snapshot_json=?,updated_at=? WHERE id=?',
                            (canonical(frozen).decode(), utc_now(), row['id']))
                        connection.execute('UPDATE tasks SET employee_reference=?,payload_json=?,pipeline_snapshot_json=?,updated_at=? WHERE id=?',
                            (canonical(frozen['employee_reference']).decode(), canonical(payload).decode(), canonical(frozen).decode(), utc_now(), row['task_id']))
                        core.repository.event('workflow_run:' + str(row['id']), 'workflow.pipeline_updated',
                            {'generation': candidate['generation'], 'source_revision': candidate['revision']}, connection=connection)
                    saved['bundle'] = candidate
                else:
                    bundle = saved['bundle']
                    if not bundle or digest(bundle)!=validated_bundle:
                        raise ContractError('流水线应用版本已变化，请核对原操作。')
                    work._selection(bundle['asset'])
                    for row in rows:
                        if row['state'] not in TERMINAL:core.repository.storage.assert_executable(row['id'])
                    for row in rows:
                        if row['state'] != 'paused': continue
                        frozen = json.loads(row['snapshot_json'])
                        target = frozen.pop('pipeline_pause', {}).get('previous_state', 'ready')
                        if frozen.get('pipeline_waiting'):
                            target='needs_approval' if frozen['pipeline_waiting']['kind']=='approval' else frozen['pipeline_waiting']['state']
                        elif (frozen.get('pipeline_result_correction') and
                                not frozen['pipeline_result_correction'].get('admitted') and
                                not frozen.get('pipeline_unresolved')):
                            target='ready'
                        elif frozen.get('pipeline_unresolved') or frozen.get('send_admitted'):
                            target = 'needs_human' if target == 'needs_human' else 'interrupted'
                        else: target = 'ready'
                        connection.execute('UPDATE workflow_runs SET state=?,snapshot_json=?,available_at=?,updated_at=? WHERE id=?',
                            (target, canonical(frozen).decode(), utc_now(), utc_now(), row['id']))
                        connection.execute('UPDATE tasks SET state=?,updated_at=? WHERE id=?', (target, utc_now(), row['task_id']))
                    saved['status'] = 'running'
                saved['revision'] += 1
                saved['quiesced_revision'] = saved['revision'] if saved['status'] == 'paused' else None
            _write(core, connection, saved)
            receipt = {'action': action, 'revision': saved['revision']}
            core.repository.event('source-pipeline-control:' + key, 'pipeline.control_committed',
                {'request_sha256': digest(request), 'receipt': receipt}, connection=connection)
    if action == 'pause': settle_pause(core, ref)
    return _project(core, data, active_ids)


def claim_filter():
    return """(json_type(wr.snapshot_json,'$.pipeline_work') IS NULL OR (
        COALESCE(json_extract(wr.snapshot_json,'$.pipeline_unresolved'),0)=0 AND
        COALESCE(json_extract(wr.snapshot_json,'$.pipeline_execution.active'),0)=0 AND
        (SELECT json_extract(e.data_json,'$.status') FROM events e WHERE e.stream=
         'source-pipeline-runtime:'||json_extract(wr.snapshot_json,'$.pipeline_work.reference.source_id')||':'||
         json_extract(wr.snapshot_json,'$.pipeline_work.reference.pipeline_source') AND e.type='pipeline.runtime_state'
         ORDER BY e.id DESC LIMIT 1)='running'))"""


def begin_execution(core, identifier):
    core.repository.storage.assert_executable(identifier)
    with core.repository.connect() as connection:
        row = connection.execute('SELECT * FROM workflow_runs WHERE id=?', (identifier,)).fetchone()
        frozen = json.loads(row['snapshot_json']); ref = frozen['pipeline_work']['reference']; saved = read(core, ref, connection)
        if row['state'] != 'running': return None
        if core._workflow_visit_count(identifier)>=workflow_policy.MAX_VISITS:
            from .source_pipeline_flow import _save
            _save(core,connection,row,frozen,'blocked')
            core.repository.event('workflow_run:'+str(identifier),'workflow.loop_guarded',{'limit':workflow_policy.MAX_VISITS},connection=connection)
            return None
        if saved['status'] != 'running':
            frozen['pipeline_pause'] = {'previous_state': 'interrupted' if frozen.get('send_admitted') else 'ready'}
            connection.execute("UPDATE workflow_runs SET state='paused',snapshot_json=? WHERE id=?", (canonical(frozen).decode(), identifier))
            connection.execute("UPDATE tasks SET state='paused' WHERE id=?", (row['task_id'],))
            return None
        if frozen.get('pipeline_unresolved'):
            raise ContractError('原工作结果尚未确认，不会重新发送。')
        if not saved['bundle'] or frozen.get('pipeline_generation')!=saved['bundle']['generation']:
            raise ContractError('岗位工作尚未应用当前流水线版本，不会执行旧版本。')
        if (frozen.get('pipeline_execution') or {}).get('active'):
            return None
        token = str(uuid.uuid4()); frozen['pipeline_execution'] = {'active': True, 'token': token}
        connection.execute('UPDATE workflow_runs SET snapshot_json=? WHERE id=?', (canonical(frozen).decode(), identifier))
        return token


def end_execution(core, identifier, token=None, *, recovery=False):
    with core.repository.connect() as connection:
        row = connection.execute('SELECT snapshot_json FROM workflow_runs WHERE id=?', (identifier,)).fetchone()
        frozen = json.loads(row[0]); marker = frozen.get('pipeline_execution') or {}
        if recovery or marker.get('token') == token:
            frozen.pop('pipeline_execution', None)
            connection.execute('UPDATE workflow_runs SET snapshot_json=? WHERE id=?', (canonical(frozen).decode(), identifier))
    settle_pause(core, frozen['pipeline_work']['reference'])


def check_chat_operation(chat_id):
    import product_store
    session = product_store.get_chat(chat_id, include_messages=False)
    context = (session or {}).get('context') or {}
    if not context.get('pipeline_work'): return
    from .device_work_services import current as device_work_service
    core = device_work_service(); identifier = context.get('employee_work', {}).get('workflow_id')
    with core.repository.connect() as connection:
        row = connection.execute('SELECT state,snapshot_json FROM workflow_runs WHERE id=?', (identifier,)).fetchone()
        frozen = json.loads(row['snapshot_json']) if row else {}; saved = read(core, context['pipeline_work']['reference'], connection)
    if (not saved['bundle'] or frozen.get('pipeline_generation')!=saved['bundle']['generation'] or
            frozen.get('work_chat_id') != chat_id or frozen.get('pipeline_generation') != context.get('pipeline_generation') or
            frozen.get('pipeline_unresolved') or not row or row['state']!='running' or
            not (frozen.get('pipeline_execution') or {}).get('active')):
        raise PermissionError('流水线已暂停或岗位版本已更新，原工作现场不能继续执行。')


def verify_state(value, scope):
    from runteams_core.employee_work_contracts import SCHEMA
    from runteams_core.employee_work_contracts import verify_frozen
    if (not isinstance(value,dict) or set(value)-{'reference','revision','status','bundle','quiesced_revision','pause_error'} or
            type(value.get('revision')) is not int or value['revision']<0 or value.get('status') not in ('running','paused')):
        raise ContractError('流水线运行状态记录无效。')
    ref=pipeline_references.checked_reference(value['reference'],scope);bundle=value['bundle']
    if value.get('quiesced_revision') not in (None,value['revision']):
        raise ContractError('流水线停止回执版本无效。')
    if bundle is None:return
    if (set(bundle)-{'configuration'}!={'revision','generation','asset','roles'} or type(bundle['generation']) is not int or
            bundle['generation']<1 or set(bundle['roles'])!={p['key'] for p in bundle['asset']['pipeline']['positions'] if p['kind']=='employee'}):
        raise ContractError('流水线应用版本记录无效。')
    if 'configuration' in bundle['asset']:
        from .employee_configuration import verify_snapshot_record
        verify_snapshot_record(bundle['asset']['configuration'],ref,bundle['revision'],bundle.get('configuration'),scope)
    elif 'configuration' in bundle:
        raise ContractError('流水线配置不属于已应用的定义。')
    for key,role in bundle['roles'].items():
        if set(role)!={'package','context','configuration'} or role['context']['asset']!=bundle['asset'] or role['context']['reference']!=ref:
            raise ContractError('流水线岗位应用记录不一致。')
        if role['context']['position_key']!=key or role['context'].get('source_revision', role['package']['revision'])!=bundle['revision']:
            raise ContractError('流水线岗位版本未统一。')
        verify_frozen({'schema':SCHEMA,'employee_reference':role['package']['reference'],'package':role['package'],
            'pipeline_work':role['context'],'pipeline_generation':bundle['generation'],'pipeline_visit':1},scope)
