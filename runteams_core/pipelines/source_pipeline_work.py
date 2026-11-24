"""Admit source pipeline stages into the existing local employee work ledger.

No installation, publication, alternate model runner or personal task is created.
Typed cross-position routing is settled by the host over the same work record.
"""
from runteams_core.pipelines import pipeline_references
from runteams_core.assets import rented_references
import copy
import json
import re
import time
import uuid
from contextlib import nullcontext

from runteams_core.storage import device_data
from runteams_core.work import workflow_policy
from runteams_core.foundation.contracts import ContractError
from runteams_core.authoring.creator_contracts import canonical, digest, relative, strict_json
from runteams_core.storage.repository import utc_now


CONTEXT = 'runteams.source-pipeline-work/1'


class WorkAdmissionUnknown(ContractError):
    def __init__(self, operation_id):
        self.operation_id = operation_id
        super().__init__('工作受理结果尚未读回，请沿原操作核对，不要重复创建。')


class StageInputError(ContractError):
    def __init__(self,message,fields=(),assets=()):
        self.fields=list(fields);self.assets=list(assets)
        super().__init__(message)


def source(ref):
    from runteams_core.pipelines.pipeline_context import current as pipeline_context
    if rented_references.is_rented(ref):
        rented_references.checked(ref);return pipeline_context().rented_revisions(ref)
    from runteams_core.authoring.source.creator_local_source import current_store
    from runteams_core.authoring.source.creator_source_revisions import Revisions
    ref = pipeline_references.checked_reference(ref)
    if not device_data.personal():
        raise PermissionError('请在个人本机工作区运行智能体团队。')
    store = current_store(device_data.identity()['cache_scope'])
    return Revisions(store, ref['source_id'])


def _entry(asset, start_column_key=None):
    if start_column_key is not None and (not isinstance(start_column_key, str) or not re.fullmatch('[a-z][a-z0-9-]{0,79}', start_column_key)):
        raise ContractError('请选择有效的开始岗位。')
    definition = asset['pipeline']
    key = start_column_key or workflow_policy.start_position(definition)
    entry = next((p for p in [*definition['positions'], *definition.get('states', [])] if p['key'] == key), None)
    if entry is None:
        raise ContractError('新工作必须选择智能体团队中实际存在的岗位。')
    return entry


def _selection(asset, start_column_key=None):
    position = _entry(asset, start_column_key)
    # Non-executing entries retain the same frozen package anchor as approval entries.
    if position['kind'] != 'employee':
        position = next(p for p in asset['pipeline']['positions'] if p['kind'] == 'employee')
    return _position(asset, position['key'])


def _position(asset, key):
    position = next((p for p in asset['pipeline']['positions'] if p['key'] == key and p['kind'] == 'employee'), None)
    if position is None:
        raise ContractError('原工作岗位不存在或已改为人工决定，不能自动丢弃或改派。')
    member = next((row for row in asset['employees'] if row['ref'] == position['employee_ref']), None)
    if member is None:
        raise ContractError('智能体团队岗位的员工引用不完整。')
    return position, member


def describe(ref, start_column_key=None):
    from runteams_core.authoring.source.creator_source_import import validate_source
    from runteams_core.pipelines.pipeline_context import current as pipeline_context
    from runteams_core.pipelines.pipeline_dependency_contracts import selector
    from runteams_core.authoring.creator_conversation_assets import extension
    ref = pipeline_references.checked_reference(ref); revisions = source(ref)
    with revisions.locked():
        revision = revisions._head(); files = revisions._files(revision)
    asset = validate_source(files)['pipelines'].get(ref['pipeline_source'])
    if asset is None: raise ContractError('智能体团队源码入口已不存在。')
    position, member = _selection(asset, start_column_key)
    description = pipeline_context().describe_member(ref, member, revision)
    employee = description['asset']
    bundle = next(b for b in employee['skill_bundles'] if b['package_key'] == position['skill_key'])
    declared = extension(bundle).get('work')
    entry = _entry(asset, start_column_key)
    return {'reference': ref, 'revision': revision, 'name': asset['pipeline']['name'],
        'position_key': entry['key'], 'position_name': entry['name'], 'kind': entry['kind'],
        'employee_source': selector(member), 'employee_name': employee['employee']['name'] if entry['kind'] == 'employee' else None,
        'skill_key': position['skill_key'], 'assets': copy.deepcopy(declared.get('assets', [])) if declared else [],
        'input_schema': copy.deepcopy(declared['input_schema']) if declared and entry['kind'] == 'employee' else {'type': 'object'}}


def _context(ref, package, position_key=None, source_revision=None):
    from runteams_core.pipelines.pipeline_context import current as pipeline_context
    if rented_references.is_rented(ref):return pipeline_context().rented_context(ref,package,position_key)
    if source_revision is not None:
        asset = frozen_catalog(ref, source_revision)['pipelines'].get(ref['pipeline_source'])
        position, member = _selection(asset) if position_key is None else _position(asset, position_key)
        from runteams_core.pipelines.pipeline_dependency_bindings import verify_binding
        verify_binding(ref, member, package, source_revision)
        return {'schema': CONTEXT, 'reference': ref, 'asset': copy.deepcopy(asset),
                'position_key': position['key'], 'source_revision': source_revision}
    from runteams_core.employees.employee_context import current as employee_context
    from runteams_core.authoring.source.source_artifacts import BuildArtifacts
    from runteams_core.authoring.creator_definitions import CATALOG_PATH
    store, _ = employee_context().package_source(package['reference'])
    _, artifacts = BuildArtifacts(store, ref['source_id']).artifacts(package['build_operation_key'])
    asset = strict_json(artifacts[CATALOG_PATH])['pipelines'].get(ref['pipeline_source'])
    if not asset or asset['schema'] != 'runteams.conversation-pipeline/v1':
        raise ContractError('原构建缺少智能体团队运行定义。')
    position, member = _selection(asset) if position_key is None else _position(asset, position_key)
    from runteams_core.foundation.identity.work_identity import source_owner
    if (member['source'] != package['reference']['employee_source'] or ref['source_id']!=package['reference']['source_id']
            or source_owner(ref)!=source_owner(package['reference'])):
        raise ContractError('智能体团队与员工运行包不一致。')
    return {'schema': CONTEXT, 'reference': ref, 'asset': copy.deepcopy(asset), 'position_key': position['key']}


def verify_context(value, package, scope=None, *, read_build=False):
    if not isinstance(value, dict) or set(value) not in ({'schema', 'reference', 'asset', 'position_key'}, {'schema', 'reference', 'asset', 'position_key', 'source_revision'}) or value.get('schema') != CONTEXT:
        raise ContractError('智能体团队岗位工作绑定无效。')
    ref = pipeline_references.checked_reference(value['reference'], scope)
    from runteams_core.authoring.creator_definitions import validate_author
    asset = value['asset']
    if not isinstance(asset, dict) or asset.get('schema') != 'runteams.conversation-pipeline/v1':
        raise ContractError('智能体团队工作定义无效。')
    validate_author('pipeline', {**asset, 'schema': 'runteams.pipeline-source/3'})
    position, member = _position(asset, value['position_key'])
    if (len({row['ref'] for row in asset['employees']}) != len(asset['employees']) or
            value['position_key'] != position['key']):
        raise ContractError('智能体团队岗位与原员工工作不一致。')
    from runteams_core.pipelines.pipeline_dependency_bindings import verify_binding
    has_dependencies = any('dependency' in row for row in asset['employees'])
    if has_dependencies != ('source_revision' in value):
        raise ContractError('智能体团队自身修订引用不完整。')
    if has_dependencies:
        from runteams_core.authoring.source.creator_source_revisions import REV
        revision = value['source_revision']
        if revision != ref['source_id'] and (not isinstance(revision, str) or not REV.fullmatch(revision)):
            raise ContractError('智能体团队自身修订无效。')
    verify_binding(ref, member, package, value.get('source_revision'))
    from runteams_core.pipelines.portable_pipeline import validate_pipeline_bindings
    validate_pipeline_bindings(asset['pipeline'], {row['ref']: [p['skill_key'] for p in asset['pipeline']['positions']
        if p['kind'] == 'employee' and p['employee_ref'] == row['ref']] for row in asset['employees']})
    if read_build and value != _context(ref, package, position['key'], value.get('source_revision')):
        raise ContractError('智能体团队岗位与原构建内容不一致。')
    return value


def prepare(ref, operation_id):
    description = describe(ref)
    package = prepare_member(ref, description['employee_source'], operation_id, description['revision'])
    context = _context(pipeline_references.checked_reference(ref), package, source_revision=description['revision'] if any('dependency' in m for m in frozen_catalog(ref, description['revision'])['pipelines'][ref['pipeline_source']]['employees']) else None)
    verify_context(context, package, read_build=True)
    return package, context


def prepare_member(ref, employee_source, operation_id, revision, *, runtime_selection=None):
    from runteams_core.pipelines.pipeline_context import current as pipeline_context
    from runteams_core.pipelines.pipeline_dependency_contracts import selector
    from runteams_core.authoring.source.creator_source_import import validate_source
    revisions = source(ref)
    asset = validate_source(revisions.files_at(revision))['pipelines'][ref['pipeline_source']]
    member = next((row for row in asset['employees'] if selector(row) == employee_source), None)
    if member is None: raise ContractError('员工不属于所选智能体团队版本。')
    deadline = time.monotonic() + 200
    while True:
        options = {'runtime_selection': runtime_selection} if runtime_selection is not None else {}
        try: return pipeline_context().prepare_member(ref, member, operation_id, revision, **options)
        except BlockingIOError:
            if time.monotonic() >= deadline: raise ContractError('员工运行包正在准备，请沿原操作稍后核对。') from None
            revisions.store.check_scope(); time.sleep(.05)


def _request(data):
    fields={'operation_id','reference','title','payload'}
    if not isinstance(data, dict) or set(data) not in (fields,fields|{'start_column_key'}):
        raise ContractError('请提供原操作编号、智能体团队引用、工作名称和输入。')
    try:
        operation = str(uuid.UUID(data['operation_id']))
    except (ValueError, TypeError, AttributeError):
        raise ContractError('工作操作编号无效。') from None
    if operation != data['operation_id']:
        raise ContractError('工作操作编号无效。')
    title = data['title']
    if not isinstance(title, str) or not title.strip() or len(title) > 200:
        raise ContractError('请填写有效的工作名称。')
    from runteams_core.authoring.definition_contracts import validate_definition
    payload = validate_definition('task_payload', copy.deepcopy(data['payload']))
    if payload.get('module_bindings') or any(payload.get('context', {}).get(k) for k in ('business_event', 'work_item')):
        raise ContractError('这类共享业务工作尚未接入本机执行。')
    if 'start_column_key' in data and (not isinstance(data['start_column_key'],str) or not re.fullmatch('[a-z][a-z0-9-]{0,79}',data['start_column_key'])):
        raise ContractError('请选择有效的开始岗位。')
    return operation, {'reference': pipeline_references.checked_reference(data['reference']), 'title': title, 'payload': payload,
        **({'start_column_key':data['start_column_key']} if 'start_column_key' in data else {})}


def _receipt(core, operation, request, connection=None):
    if connection is None:
        with core.repository.connect() as connection:
            return _receipt(core, operation, request, connection)
    row = connection.execute("SELECT data_json FROM events WHERE stream=? AND type='pipeline.work_admitted' ORDER BY id DESC LIMIT 1",
        ('source-pipeline-operation:' + operation,)).fetchone()
    if row is None:
        return None
    value = json.loads(row[0])
    if value['request_sha256'] != digest(request):
        raise ContractError('原操作编号已用于其他工作内容。')
    return value['workflow_id']


def _project_execution_names(attempts, employee_context):
    from runteams_core.employees.source_employee_runtime import units

    names_by_package = {}
    for attempt in attempts:
        order = attempt['input_json']
        package = order.get('package')
        skill_key = (order.get('payload') or {}).get('skill_key')
        if not package or not skill_key:
            continue
        key = digest(package)
        if key not in names_by_package:
            try:
                asset = employee_context.package_asset(package)
                names_by_package[key] = {unit['key']: unit['name'] for unit in units(asset)}
            except (KeyError, OSError, ValueError):
                # The original package may have been removed. The recorded stage is still available.
                names_by_package[key] = {}
        name = names_by_package[key].get(skill_key)
        if name:
            attempt['work_name'] = name


def _authorized_work(connection, ref, identifier):
    row = connection.execute(
        'SELECT w.snapshot_json, w.state, w.cursor_key, w.task_id, t.trashed_at FROM workflow_runs w '
        'JOIN tasks t ON t.id=w.task_id WHERE w.id=?',
        (identifier,)).fetchone()
    frozen = json.loads(row['snapshot_json']) if row else {}
    context = frozen.get('pipeline_work') or {}
    if context.get('reference') != ref:
        raise PermissionError('工作不属于这个智能体团队。')
    verify_context(context, frozen['package'])
    return row, frozen


def work_activity(core, ref, identifier, run_id):
    from runteams_core.pipelines.pipeline_execution_activity import ActivityStream, observe
    core._actor(); ref = pipeline_references.checked_reference(ref)
    with core.repository.read_snapshot() as connection:
        row, frozen = _authorized_work(connection, ref, identifier)
        if row['trashed_at'] or row['state'] != 'running' or frozen.get('employee_run_id') != run_id:
            return ActivityStream()
        active = connection.execute(
            "SELECT 1 FROM employee_runs WHERE id=? AND workflow_run_id=? AND position_key=? AND state='running'",
            (run_id, identifier, row['cursor_key'])).fetchone()
        if not active:
            return ActivityStream()
        return observe(core, identifier, run_id, frozen.get('work_chat_id'))


def work(core, ref, identifier):
    core._actor(); ref = pipeline_references.checked_reference(ref)
    with core.repository.read_snapshot() as connection:
        _, frozen = _authorized_work(connection, ref, identifier)
        from runteams_core.employees.employee_context import current as employee_context
        employees = employee_context()
        result = employees.work_detail(core, identifier)
        attempts = result.get('employee_runs', ())
        _project_execution_names(attempts, employees)
        if result['state'] == 'running':
            from runteams_core.pipelines.pipeline_execution_activity import read as read_activity
            run_id = frozen.get('employee_run_id')
            active = next((attempt for attempt in attempts if attempt['id'] == run_id
                           and attempt['state'] == 'running'
                           and attempt['position_key'] == result['cursor_key']), None)
            if active:
                activity = read_activity(core, identifier, run_id, frozen.get('work_chat_id'))
                if activity:
                    active['live_activity'] = activity
        from runteams_core.automation.scheduled_employee_chat import FAILURE_IN_CHAT, recorded_failure_reason
        for attempt in attempts:
            if attempt['state'] != 'failed':
                continue
            output = attempt['output_json']
            if (output.get('transport_status') == 'failed'
                    and output.get('issues') in (None, [], [FAILURE_IN_CHAT])):
                reason = recorded_failure_reason(attempt['input_json'].get('chat_id'),
                                                 attempt['created_at'], attempt['updated_at'])
                if reason:
                    attempt['failure_reason'] = reason
        from runteams_core.pipelines.pipeline_input_contracts import task_input_contract
        from runteams_core.pipelines.pipeline_task_configuration import project
        from runteams_core.pipelines.source_pipeline_flow import feedback_request, launch_failure, retry_mode, signing_setup
        from runteams_core.pipelines.source_pipeline_control import read
        bundle = read(core,ref,connection)['bundle']
        error = launch_failure(connection, result, frozen)
        result['retry_mode'] = retry_mode(result['state'],result['cursor_key'],frozen,
                                          bundle['roles'] if bundle else {}, launch_error=error)
        if error:
            result['state'] = 'blocked'
            result['launch_error'] = error
        needs_feedback = result['state'] in ('blocked', 'needs_human')
        signing = signing_setup(frozen) if needs_feedback else None
        waiting = frozen.get('pipeline_waiting') or {}
        return {'pipeline_reference': ref, 'position_key': result['cursor_key'],
            'workflow': result, 'input_contract': task_input_contract(result['snapshot_json'], result['cursor_key']),
            'task_configuration': project(result, result['snapshot_json']),
            'signing_setup': signing,
            'human_request': feedback_request(frozen) if needs_feedback and not signing and waiting.get('kind')=='result' else None,
            'storage_scope': 'device'}


def operation(core, data):
    core._actor(); key, request = _request(data)
    identifier = _receipt(core, key, request)
    return {'operation_id': key, 'status': 'unknown' if identifier is None else 'committed',
        **({} if identifier is None else {'result': work(core, request['reference'], identifier)})}


def retry_before_send(core, identifier):
    """Only an unsent stage may re-enter the existing scheduler as the same work."""
    core._actor()
    with core.repository.connect() as connection:
        original=connection.execute('SELECT snapshot_json FROM workflow_runs WHERE id=?',(identifier,)).fetchone()
    if original is None:raise ContractError('原智能体团队工作不存在。')
    expected=json.loads(original[0])
    verify_context(expected.get('pipeline_work'),expected['package'],read_build=True)
    from runteams_core.employees.employee_context import current as employee_context
    employee_context().validate_package(expected['package'])
    if expected.get('configuration') is not None:

        employee_context().validate_package_configuration(expected['package'],expected['configuration'])
    with core.repository.connect() as connection:
        connection.execute('BEGIN IMMEDIATE')
        row = connection.execute('SELECT state,task_id,snapshot_json FROM workflow_runs WHERE id=?', (identifier,)).fetchone()
        if row is None:
            raise ContractError('原智能体团队工作不存在。')
        frozen = json.loads(row['snapshot_json']) if row else {}
        if digest(frozen)!=digest(expected):raise ContractError('工作状态已变化，请核对原工作。')
        from runteams_core.pipelines.source_pipeline_control import bundle_for_work, read
        runtime=read(core,frozen['pipeline_work']['reference'],connection)
        bundle_for_work(core, connection, frozen)
        if (runtime['status']!='running' or
                frozen.get('pipeline_unresolved') or frozen.get('send_admitted') or
                row['state'] not in ('needs_human', 'interrupted', 'failed')):
            raise ContractError('原工作已发送或仍在运行，请先核对原结果，不会重复发送。')
        now = utc_now()
        connection.execute("UPDATE workflow_runs SET state='ready',available_at=?,updated_at=? WHERE id=?", (now, now, identifier))
        connection.execute("UPDATE tasks SET state='ready',updated_at=? WHERE id=?", (now, row['task_id']))
        core.repository.event('workflow_run:' + str(identifier), 'workflow.retry_scheduled', {'boundary': 'before_send'}, connection=connection)
    return core.workflow(identifier)


def _project(core, request, identifier, key):
    try:
        return work(core, request['reference'], identifier)
    except PermissionError:
        raise
    except Exception as error:
        raise WorkAdmissionUnknown(key) from error


def stage_payload(package, context, payload, *, updating=False):
    position, _ = _position(context['asset'], context['position_key'])
    payload = copy.deepcopy(payload)
    if not updating and payload.get('skill_key') not in (None, '', position['skill_key']):
        raise ContractError('工作技能必须使用智能体团队岗位绑定。')
    payload['skill_key'] = position['skill_key']
    from runteams_core.employees.employee_context import current as employee_context
    from runteams_core.authoring.creator_conversation_assets import extension
    employee = employee_context().package_asset(package)
    bundle = next(b for b in employee['skill_bundles'] if b['package_key'] == position['skill_key'])
    declared_work = extension(bundle).get('work')
    if declared_work:
        from jsonschema import Draft202012Validator
        error = next(Draft202012Validator(declared_work['input_schema']).iter_errors(payload.get('parameters', {})), None)
        if error:
            fields=([str(next(iter(error.absolute_path)))] if error.absolute_path else
                [k for k in error.validator_value if k not in error.instance] if error.validator=='required' and isinstance(error.instance,dict) else [])
            raise StageInputError('工作输入不符合岗位技能声明：' + error.message,fields)
        missing=[slot['name'] for slot in declared_work.get('assets',[]) if slot.get('required') and
            not payload.get('asset_bindings',{}).get(slot['name'])]
        if missing:raise StageInputError('工作缺少岗位必需资料：'+'、'.join(missing),assets=missing)
    payload.setdefault('context', {})['pipeline_stage'] = {
        'name': context['asset']['pipeline']['name'], 'position_key': position['key'],
        'position_name': position['name'], 'handoff_owner': 'host_after_acceptance'}
    standard = context['asset']['pipeline'].get('team_standard')
    if standard:
        payload['context']['pipeline_stage']['team_standard'] = standard
    return payload


def stage_snapshot(package, context, configuration):
    from runteams_core.employees.employee_context import current as employee_context
    from runteams_core.foundation.identity.work_identity import principal
    employee = employee_context().package_asset(package)
    frozen = {'schema': 'runteams.employee-chat-work/v1', 'employee_reference': package['reference'],
        'package': package, 'employee': {k: employee['employee'][k] for k in ('name', 'avatar')},
        'name': context['asset']['pipeline']['name'], 'definition': {'positions': [], 'edges': []},
        'source': {'actor_id': principal(device_data.identity())}, 'pipeline_work': context}
    if configuration is not None:
        frozen['configuration'] = configuration
    return frozen


def create(core, data, *, rerun=None, repeat_order=None, prepare_inputs=None,
           expected_revision=None, schedule_origin=None):
    core._actor(); key, request = _request(data)
    previous = _receipt(core, key, request)
    if previous is not None:
        return _project(core, request, previous, key)
    from runteams_core.pipelines import source_pipeline_control as control
    ref = request['reference']
    revisions = source(ref)
    active = control.read(core, ref)
    if active['status'] != 'running':
        raise ContractError('智能体团队已暂停，不能开始新工作。')
    with revisions.locked():
        revision = revisions._head()
    if expected_revision is not None and revision != expected_revision:
        raise ContractError('智能体团队源码已有更新，请重新核对本次工作。')
    candidate = active['bundle']
    if not candidate or candidate['revision'] != revision:
        candidate = control.prepare_bundle(ref, key, revision)
    position, _ = _selection(candidate['asset'], request.get('start_column_key'))
    role = candidate['roles'][position['key']]
    from runteams_core.employees.employee_context import current as employee_context
    employee_context().validate_package(role['package'])
    verify_context(role['context'], role['package'], read_build=True)
    with core.repository.connect() as connection, revisions.locked():
        if rented_references.is_rented(ref):
            from runteams_core.pipelines.pipeline_context import current as pipeline_context
            candidate = pipeline_context().refresh_rented_runtime(ref, candidate)
        else:
            from runteams_core.pipelines import pipeline_position_runtime as position_runtime
            candidate = position_runtime.refresh_bundle(ref, candidate)
        connection.execute('BEGIN IMMEDIATE')
        previous = _receipt(core, key, request, connection)
        if previous is not None:
            identifier = previous
        else:
            if revisions._head() != candidate['revision']:
                raise ContractError('智能体团队源码已有更新，请重新核对本次工作。')
            selected, generation = control.admit(connection, core, request['reference'], candidate,request.get('start_column_key'))
            package, context = selected['package'], selected['context']
            from runteams_core.pipelines import source_pipeline_flow as flow
            bundle=control.read(core,request['reference'],connection)['bundle']
            cursor=request.get('start_column_key') or workflow_policy.start_position(context['asset']['pipeline'])
            now = utc_now()
            initial_input = request['payload']
            if prepare_inputs is not None:
                task_id = connection.execute(
                    'INSERT INTO tasks(employee_reference,title,payload_json,state,start_column_key,created_at,updated_at) '
                    'VALUES(?,?,?,?,?,?,?)',
                    (canonical(package['reference']).decode(), request['title'], canonical(initial_input).decode(),
                     'ready', cursor, now, now)).lastrowid
                initial_input = prepare_inputs(task_id)
            frozen, payload = flow.initial(core, connection, selected, bundle, initial_input, cursor)
            frozen['initial_pipeline_input'] = copy.deepcopy(initial_input)
            if rerun is not None:
                frozen['rerun'] = {key: rerun[key] for key in ('source_run_key', 'knowledge')}
            if repeat_order is not None:
                frozen['repeat_order'] = repeat_order
            if schedule_origin is not None:
                frozen['schedule_origin'] = schedule_origin
            elif rerun is None:
                frozen['manual_order'] = True
            encoded = canonical(frozen).decode()
            if prepare_inputs is not None:
                connection.execute('UPDATE tasks SET payload_json=?,pipeline_snapshot_json=? WHERE id=?',
                                   (canonical(payload).decode(), encoded, task_id))
            else:
                task_id = connection.execute(
                    'INSERT INTO tasks(employee_reference,title,payload_json,state,start_column_key,pipeline_snapshot_json,created_at,updated_at) '
                    'VALUES(?,?,?,?,?,?,?,?)',
                    (canonical(package['reference']).decode(), request['title'], canonical(payload).decode(),
                     'ready', cursor, encoded, now, now)).lastrowid
            identifier = connection.execute('INSERT INTO workflow_runs(task_id,state,available_at,cursor_key,snapshot_json,created_at,updated_at) VALUES(?,?,?,?,?,?,?)',
                (task_id, 'ready', now, cursor, encoded, now, now)).lastrowid
            entry = _entry(context['asset'], cursor)
            if entry['kind']=='approval':
                frozen['pipeline_waiting']={'kind':'approval','position_key':cursor,'source_run_id':None}
                row=flow._row(connection,identifier)
                flow._save(core,connection,row,frozen,'needs_approval',cursor)
            elif entry['kind'] in ('done', 'dropped', 'pool'):
                state = {'done': 'completed', 'dropped': 'canceled', 'pool': 'blocked'}[entry['kind']]
                flow._save(core, connection, flow._row(connection, identifier), frozen, state, cursor)
            core.repository.event('task:' + str(task_id), 'task.created',
                {'task_id': task_id, 'pipeline_reference': request['reference'], 'title': request['title']}, connection=connection)
            core.repository.event('workflow_run:' + str(identifier), 'workflow.created',
                {'task_id': task_id, 'pipeline_reference': request['reference'], 'position_key': cursor}, connection=connection)
            core.repository.event('source-pipeline-operation:' + key, 'pipeline.work_admitted',
                {'request_sha256': digest(request), 'workflow_id': identifier}, connection=connection)
            if rerun is not None:
                from runteams_core.automation.automation_rerun import record
                record(core, connection, rerun, identifier, task_id, request['title'])
            from runteams_core.pipelines.pipeline_task_report import sync
            sync(core, connection, identifier)
    return _project(core, request, identifier, key)


def frozen_catalog(ref, revision):
    """Rebuild only immutable definition bytes; this never runs creator code."""
    from runteams_core.authoring.source.creator_source_import import validate_source
    from runteams_core.authoring.creator_conversation_assets import compile_catalog
    files = source(ref).files_at(revision)
    return compile_catalog(files, validate_source(files))
