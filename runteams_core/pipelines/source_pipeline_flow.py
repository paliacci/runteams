"""Typed handoffs in the original employee work ledger, never a model runner.

Employees submit professional results. Only the host selects declared edges,
accepts inputs, owns the cursor, and creates the next visit of the SAME work.
"""
from runteams_core.pipelines import pipeline_references
import copy
import json
import uuid
import hashlib
from pathlib import Path
import tempfile

from runteams_core.pipelines import source_pipeline_work as work, source_pipeline_control as control
from runteams_core.work import workflow_policy
from runteams_core.foundation.contracts import (
    ContractError, PIPELINE_COMPLETE_HERE, PIPELINE_STATUS_FIRST, PIPELINE_WAIT_FOR_INPUT, normalize_work_result,
)
from runteams_core.authoring.creator_contracts import canonical, digest
from runteams_core.storage.repository import utc_now

APPLE_DEVICE_SIGNING = 'apple_device_signing'
FIELD_INPUT_MODES = ('fields', 'fields_and_text')
TEXT_INPUT_MODES = ('text', 'fields_and_text')
HUMAN_BLOCKER_SCHEMA = {'type': 'object', 'properties': {
    'kind': {'type': 'string', 'enum': ['information', 'authorization', 'decision']},
    'user_action': {'type': 'string', 'minLength': 1, 'maxLength': 240,
                    'description': 'The exact missing information, access or decision this person must provide.'},
    'reason': {'type': 'string', 'minLength': 1, 'maxLength': 400,
               'description': 'What you checked or attempted and why this dependency cannot be resolved within existing access or by a configured employee handoff.'},
}, 'required': ['kind', 'user_action', 'reason'], 'additionalProperties': False}
HUMAN_REQUEST_SCHEMA = {'type': 'object', 'properties': {
    'blocker': HUMAN_BLOCKER_SCHEMA,
    'question': {'type': 'string', 'minLength': 1, 'maxLength': 300},
    'options': {'type': 'array', 'minItems': 1, 'maxItems': 4, 'items': {
        'type': 'object', 'properties': {
            'label': {'type': 'string', 'minLength': 1, 'maxLength': 100},
            'description': {'type': 'string', 'maxLength': 300},
            'recommended': {'type': 'boolean'},
            'input_mode': {'type': 'string', 'enum': ['none', 'fields', 'text', 'fields_and_text'],
                'description': 'Use none for a decision alone, fields for existing task fields, text for a '
                               'required one-off answer, or fields_and_text for both.'},
            'configuration_fields': {'type': 'array', 'maxItems': 40, 'uniqueItems': True,
                'items': {'type': 'string', 'pattern': '^[a-z][a-z0-9_-]{0,79}$'},
                'description': 'Existing task configuration keys to edit when this option is chosen.'},
            'response_prompt': {'type': 'string', 'minLength': 1, 'maxLength': 240,
                'description': 'Tell the user exactly what to type for text and fields_and_text. Never ask for credentials.'},
        }, 'required': ['label'], 'additionalProperties': False}},
}, 'required': ['question', 'options'], 'additionalProperties': False,
   'description': 'When a person must unblock this work, ask one concrete question and offer distinct feasible responses. '
                  'The user may also write a custom answer. Mark at most one option recommended. '
                  'Keep options in the user’s language; they are replies, not approvals or automatic actions.'}

APPROVAL_REQUEST_SCHEMA = copy.deepcopy(HUMAN_REQUEST_SCHEMA)
APPROVAL_REQUEST_SCHEMA['properties'].pop('blocker')
approval_option_schema = APPROVAL_REQUEST_SCHEMA['properties']['options']['items']
for key in ('configuration_fields', 'input_mode', 'response_prompt'):
    approval_option_schema['properties'].pop(key)
approval_option_schema['properties']['decision'] = {'type': 'string', 'minLength': 1, 'maxLength': 160}
approval_option_schema['required'].append('decision')
APPROVAL_REQUEST_SCHEMA['description'] = (
    'For the approval reached by your completed result, write a task-specific question and one clear action label '
    'per configured decision. Use the exact decision keys in stage.downstream_approvals. '
    'Labels describe what the person authorizes. Do not append arrows or employee names.'
)

SUBMITTED_HUMAN_REQUEST_SCHEMA = copy.deepcopy(HUMAN_REQUEST_SCHEMA)
SUBMITTED_HUMAN_REQUEST_SCHEMA['required'].append('blocker')
SUBMITTED_HUMAN_REQUEST_SCHEMA['properties']['options']['items']['required'].append('input_mode')
SUBMITTED_HUMAN_REQUEST_SCHEMA['description'] = (
    'Ask only when a concrete blocker needs human action. State the required action and what you checked. '
    'Options must resolve that dependency, and each option must specify how to collect its input. '
    'Mark at most one recommended. Replies do not authorize an approval or select a workflow route.'
)

INPUT_SCHEMA = {'type': 'object', 'properties': {
    'operation': {'type': 'string', 'enum': ['read', 'submit', 'read_report', 'export_report']},
    'operation_id': {'type': 'string'}, 'report_id': {'type': 'integer', 'minimum': 1},
    'result': {'type': 'object', 'properties': {
        'status': {'type': 'string', 'enum': ['completed','blocked','needs_human','failed']},
        'title': {'type': 'string', 'minLength': 1, 'maxLength': 80, 'pattern': r'^[^\r\n]+$',
                  'description': 'Short, single-line title in the user’s language. Name the concrete result or blocker supported by this execution.'},
        'setup_required': {'type': 'string', 'enum': [APPLE_DEVICE_SIGNING],
                           'description': 'Use apple_device_signing only when blocked on iPhone development signing, after identifying the missing team or signing materials.'},
        'human_request': SUBMITTED_HUMAN_REQUEST_SCHEMA,
        'approval_request': APPROVAL_REQUEST_SCHEMA,
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
        raise ContractError('原智能体团队工作不存在。')
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
    if state == 'completed' and row['state'] != state:
        from runteams_core.pipelines.pipeline_task_report import save_completion
        save_completion(core, connection, row['id'])


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


def _declared_handoff(definition, source, target, output):
    return {p['key']: output[p['key']] for p in definition.get('parameters', [])
        if p.get('source') == 'employee' and p.get('display') == 'handoff'
        and p.get('type') != 'secret' and source in p.get('writers', [])
        and target in p.get('visible_to', []) and p['key'] in output}


def stage_assignment(frozen, context=None):
    context = frozen['pipeline_work'] if context is None else context
    position, _ = work._position(context['asset'], context['position_key'])
    history = frozen.get('pipeline_history') or []
    entry = history[0]['snapshot']['pipeline_work'] if history else frozen['pipeline_work']
    objective = frozen['pipeline_input']['objective']
    if position['key'] == entry['position_key']:
        return {'assignment': objective}
    assignment = f"在「{position['name']}」岗位完成当前阶段的工作，并按本岗技能合同提交结果。"
    if position.get('description'):
        assignment += '\n' + position['description']
    if position.get('prompt'):
        assignment += '\n' + position['prompt']
    return {'assignment': assignment, 'project_background': objective}


def stage_prompt(stage):
    prompt = stage['assignment']
    if 'project_background' in stage:
        prompt += ('\n\n按本岗技能合同、当前交接和输入工作。project_background 是项目最初的说明，'
                   '用于理解范围和验收约束；其中上游岗位的动作不属于本岗。'
                   '上游反馈中只把影响本岗工作或验收的问题视为当前阻塞。'
                   'approval_history 是本任务已记录的人工决定，适用范围以决定说明为准。')
    return prompt


def add_approval_history(connection, identifier, context, stage):
    """Expose recorded decisions for this task as history, without granting approval."""
    names = {p['key']: p['name'] for p in context['asset']['pipeline']['positions'] if p['kind'] == 'approval'}
    if not names:
        return
    latest = {}
    for row in connection.execute(
            "SELECT data_json FROM events WHERE stream=? AND type='workflow.approval_decided' ORDER BY id DESC",
            ('workflow_run:' + str(identifier),)):
        decision = json.loads(row[0])
        key = decision.get('position_key')
        if key in names and key not in latest:
            latest[key] = {'position_name': names[key], 'decision': decision['decision'], 'note': decision.get('note', '')}
        if len(latest) == len(names):
            break
    if latest:
        stage['approval_history'] = list(reversed(latest.values()))


def payload_for(core, connection, frozen, role, extra=None):
    context = role['context']; key = context['position_key']
    payload = copy.deepcopy(frozen['pipeline_input'])
    payload['parameters'] = parameters(core, connection, frozen, key, role['package'], extra)
    payload['skill_key'] = work._position(context['asset'], key)[0]['skill_key']
    payload = work.stage_payload(role['package'], context, payload, updating=True)
    stage = payload['context']['pipeline_stage']
    # Older tasks retain the historical default instead of adopting a later device change.
    stage['language_policy'] = copy.deepcopy(frozen.get('language_policy', {'communication_language': 'zh-CN'}))
    stage.update(stage_assignment(frozen, context))
    stage['feedback_configuration_fields'] = _feedback_configuration_fields(context)
    stage['handoff_owner'] = 'host_after_acceptance'
    graph = context['asset']['pipeline']
    outgoing = [edge for edge in graph['edges'] if edge['from'] == key]
    in_place = {PIPELINE_WAIT_FOR_INPUT, PIPELINE_COMPLETE_HERE}
    if graph.get('routing_policy') != PIPELINE_STATUS_FIRST:
        in_place.remove(PIPELINE_COMPLETE_HERE)
    stage['downstream_positions'] = [edge['to'] for edge in outgoing if edge['to'] not in in_place]
    destinations = {target['key']: target for target in graph['positions'] + graph.get('states', [])}
    stage['result_routes'] = [
        {'when': edge.get('when') or 'completed', 'destination': (
            {'kind': edge['to']} if edge['to'] in in_place else
            {key: destinations[edge['to']][key] for key in ('kind', 'name')})}
        for edge in outgoing
    ]
    stage['downstream_approvals'] = [
        {'position_key': position['key'], 'name': position['name'], 'prompt': position.get('prompt', ''),
         'decisions': approval_decisions(graph, position['key'])}
        for position in graph['positions']
        if position['kind'] == 'approval' and position['key'] in stage['downstream_positions']
    ]
    stage['result_submission'] = ('Use runteams_pipeline_work read, then submit a typed result before finishing. '
        'Include a short result.title naming the verified outcome or blocker, in the same language as the summary. '
        'When blocked on a user reply or choice, or a completed business outcome routes to wait-for-input, '
        'include result.human_request with a question and concrete options. '
        'When handing off to an approval in stage.downstream_approvals, include result.approval_request '
        'with a contextual question and user-facing labels for that approval’s configured decisions. '
        'Each human_request option must specify input_mode. Use none for a decision alone; fields with configuration_fields '
        'for existing keys in stage.feedback_configuration_fields; text with a specific response_prompt for a one-off '
        'required answer; or fields_and_text when both are needed. Describe the choice separately from what to fill in. '
        'Complete all authorized work that can still proceed. Use result_routes to hand off employee-owned work. '
        'Do not ask whether an employee should continue work already within scope. For a human_request, fill blocker with '
        'the exact human action and what you checked to establish it is needed. Each option must help resolve that dependency. '
        'Use the declared setup path for signing configuration. '
        'A chat reply is not a handoff.')
    if any(edge['to'] == PIPELINE_WAIT_FOR_INPUT for edge in outgoing):
        stage['result_submission'] += ' When a result asks the user for materials, explain exactly what is missing and what will let this stage continue.'
    stage['reports']=_reports(core,connection,frozen,role)
    if frozen.get('pipeline_history'):
        stage['previous_completed_visits'] = 0
        handoffs = []
        for entry in frozen['pipeline_history']:
            previous = entry['snapshot']
            source = previous['pipeline_work']['position_key']
            result = (previous.get('pipeline_submission') or {}).get('result') or {}
            if not previous.get('pipeline_applied_result') or result.get('status') != 'completed':
                continue
            if source == key:
                stage['previous_completed_visits'] += 1
            visible = _declared_handoff(context['asset']['pipeline'], source, key, result['output'])
            if visible and len(canonical(visible)) <= 4096:
                handoffs.append({'position_key': source, 'values': visible})
        if handoffs:
            stage['previous_handoffs'] = handoffs
    if frozen.get('pipeline_feedback'):
        stage['feedback'] = copy.deepcopy(frozen['pipeline_feedback'])
    if frozen.get('pipeline_response'):
        stage['human_response'] = frozen['pipeline_response']
    return payload


def initial(core, connection, role, bundle, payload,start_column_key=None):
    from runteams_core.agents.language_policy import snapshot
    frozen = work.stage_snapshot(role['package'], role['context'], role['configuration'])
    frozen.update(language_policy=snapshot(), pipeline_generation=bundle['generation'], pipeline_visit=1,
        pipeline_input=copy.deepcopy(payload), pipeline_lineage=[])
    if payload.get('skill_key') not in (None,'',work._position(role['context']['asset'],role['context']['position_key'])[0]['skill_key']):
        raise ContractError('工作技能必须使用智能体团队岗位绑定。')
    declarations = bundle['asset']['pipeline'].get('parameters', [])
    if declarations:
        allowed = {p['key'] for p in declarations if p.get('source') == 'user' and p['type'] != 'secret'}
        if set(payload.get('parameters', {})) - allowed:
            raise ContractError('任务只能提供已声明的用户参数，员工产出不能由任务创建者代填。')
    from runteams_core.pipelines.pipeline_task_configuration import fields, validate_values
    setup = fields(frozen)
    setup_keys = {p['key'] for p in setup}
    validate_values(setup, {k:v for k,v in payload.get('parameters', {}).items() if k in setup_keys})
    entry=start_column_key or workflow_policy.start_position(bundle['asset']['pipeline'])
    if work._entry(bundle['asset'], entry)['kind'] != 'employee':
        return frozen,copy.deepcopy(payload)
    return frozen, payload_for(core, connection, frozen, role)


def _human_request(value, *, schema=HUMAN_REQUEST_SCHEMA):
    from jsonschema import Draft202012Validator

    if not Draft202012Validator(schema).is_valid(value):
        raise ContractError('反馈选项须包含一个问题和一至四个可选回答。')
    question = value['question'].strip()
    options = [{**item, 'label': item['label'].strip()} for item in value['options']]
    labels = [item['label'].casefold() for item in options]
    if (not question or any(not label or '\n' in label or '\r' in label for label in labels)
            or len(set(labels)) != len(labels) or sum(item.get('recommended', False) for item in options) > 1):
        raise ContractError('反馈选项须各不相同，并且最多推荐一项。')
    for option in options:
        mode = option.get('input_mode')
        if mode is None:
            if 'response_prompt' in option:
                raise ContractError('请为需要填写说明的选项声明输入方式。')
            continue
        if (mode in FIELD_INPUT_MODES) != bool(option.get('configuration_fields')):
            raise ContractError('需要填写任务配置的选项必须列出字段，其他选项不能附带字段。')
        if mode in TEXT_INPUT_MODES:
            prompt = option.get('response_prompt', '').strip()
            if not prompt:
                raise ContractError('需要文字回答的选项必须说明要填写什么。')
            option['response_prompt'] = prompt
        elif 'response_prompt' in option:
            raise ContractError('无需文字回答的选项不能附带输入提示。')
    normalized = {'question': question, 'options': options}
    if 'blocker' in value:
        blocker = {key: item.strip() for key, item in value['blocker'].items()}
        if not all(blocker.values()):
            raise ContractError('请说明用户具体需要做什么，以及你已做过哪些核对。')
        normalized['blocker'] = blocker
    return normalized


def has_input_contract(request):
    return bool(request and any('input_mode' in option for option in request['options']))


def _require_input_contract(request):
    if request and any('input_mode' not in option for option in request['options']):
        raise ContractError('请为每个反馈选项声明 input_mode：none、fields、text 或 fields_and_text。')


def approval_decisions(graph, position):
    return [edge.get('when') or 'completed' for edge in graph['edges'] if edge['from'] == position]


def _approval_request(value, graph, position):
    request = _human_request(value, schema=APPROVAL_REQUEST_SCHEMA)
    decisions = [option['decision'] for option in request['options']]
    allowed = set(approval_decisions(graph, position))
    if len(decisions) != len(set(decisions)) or set(decisions) != allowed:
        raise ContractError('审批选项须与当前环节配置的决定一一对应。')
    return request


def _feedback_configuration_fields(context):
    position = context.get('position_key')
    fields = (context.get('asset') or {}).get('pipeline', {}).get('parameters', [])
    return [{key: field[key] for key in ('key', 'label', 'type', 'note') if key in field}
            for field in fields if field.get('source') == 'user'
            and field.get('display') == 'setup' and field.get('type') != 'secret'
            and (not field.get('visible_to') or position in field['visible_to'])]


def _feedback_fields(context, keys):
    allowed = {field['key'] for field in _feedback_configuration_fields(context)}
    if set(keys) - allowed:
        raise ContractError('反馈选项只能要求填写本岗位可用的任务配置。')


def feedback_request(frozen):
    waiting = frozen.get('pipeline_waiting') or {}
    request = human_request(waiting)
    if not request:
        return None
    context = frozen.get('pipeline_work') or {}
    for option in request['options']:
        keys = option.get('configuration_fields', [])
        _feedback_fields(context, keys)
        if keys:
            option['configuration_fields'] = list(keys)
    return request


def human_request(waiting):
    result = waiting.get('result') or {}
    request = waiting.get('human_request') or result.get('human_request')
    if request is None and isinstance(result.get('output'), dict):
        output = result['output']
        if output.get('question') and output.get('options'):
            request = {key: output[key] for key in ('question', 'options')}
    if request is not None:
        try:
            return _human_request(request)
        except ContractError:
            # Older work may use its own output shape. Keep custom reply available.
            pass
    return None


def _result(package, context, result):
    if not isinstance(result,dict) or set(result)-{'schema','status','title','setup_required','human_request','approval_request','summary','output','artifacts','issues','work_done','actions'}:
        raise ContractError('岗位结果包含未声明字段。result 必须包含 status、summary、output；技能 output_schema 的字段全部放在 result.output 内，不能直接放在 result。')
    value = normalize_work_result(result)
    if 'title' in result:
        title = result['title']
        if not isinstance(title, str) or not title.strip() or len(title) > 80 or title.splitlines() != [title]:
            raise ContractError('岗位结果标题须为 80 字以内的单行文字。')
        value['title'] = title.strip()
    if 'setup_required' in result:
        if result['setup_required'] != APPLE_DEVICE_SIGNING or value['status'] not in ('blocked', 'needs_human'):
            raise ContractError('只有等待真机签名配置的岗位结果可声明此缺项。')
        from runteams_core.configuration.configuration_schema import fields
        from runteams_core.employees.employee_context import current as employee_context
        definition = employee_context().package_asset(package)['employee'].get('configuration')
        if not definition or not any(field['key'] == 'apple_team_id' and field['type'] == 'text' for field in fields(definition)):
            raise ContractError('原岗位没有可保存的 Apple Team ID 配置。')
        value['setup_required'] = APPLE_DEVICE_SIGNING
    if 'human_request' in result:
        from runteams_core.work.work_ledger import WorkLedger
        graph = (context.get('asset') or {}).get('pipeline', {})
        edge = WorkLedger._matching_edge(graph, context.get('position_key'), value)
        material_wait = (value['status'] == 'completed' and graph.get('routing_policy') == PIPELINE_STATUS_FIRST
                         and edge and edge['to'] == PIPELINE_WAIT_FOR_INPUT)
        if (value['status'] not in ('blocked', 'needs_human') and not material_wait) or value.get('setup_required'):
            raise ContractError('只有等待人工回答的岗位结果可以提交反馈选项。')
        value['human_request'] = _human_request(result['human_request'])
        for option in value['human_request']['options']:
            _feedback_fields(context, option.get('configuration_fields', []))
    if not isinstance(value['output'], dict) or value['artifacts'] or value.get('actions'):
        raise ContractError('岗位结果使用结构化 output；文档由正式汇报保存，不接收自行授予权限的成果或动作。')
    if 'approval_request' in result:
        from runteams_core.work.work_ledger import WorkLedger
        graph = context['asset']['pipeline']
        edge = WorkLedger._matching_edge(graph, context['position_key'], value)
        if value['status'] != 'completed' or not edge or not any(
                p['key'] == edge['to'] and p['kind'] == 'approval' for p in graph['positions']):
            raise ContractError('只有将交给人工审批的结果可以附带审批选项。')
        value['approval_request'] = _approval_request(result['approval_request'], graph, edge['to'])
    if value['status'] == 'completed':
        unit = declared(package, work._position(context['asset'], context['position_key'])[0]['skill_key'])
        if unit:
            from jsonschema import Draft202012Validator
            error = next(Draft202012Validator(unit['output_schema']).iter_errors(value['output']), None)
            if error:
                raise ContractError('岗位产出不符合技能声明：' + error.message)
    return value


class HandoffInputRejected(ContractError):
    def __init__(self, issue, owners):
        self.issue = issue
        super().__init__('下游尚不能接收，请由' + owners + '补齐后再提交：' + issue['message'])


class ApprovalBriefMissing(ContractError):
    def __init__(self, position, decisions):
        self.approval = {'position': position, 'decisions': decisions}
        super().__init__('请在 approval_request 中为下一人工审批环节生成问题和选项后再提交。')


class WorkflowVisitChanged(ContractError):
    pass


def _rejected_completed_submission(core,connection,frozen):
    """Require a completed turn and a reproducible result or handoff rejection.

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
        try:_recheck_submission(core, connection, frozen, args.get('result'))
        except ContractError as error:
            # This exact validator must explain the host-recorded rejection.
            # The expanded envelope diagnostic also recognizes its old prefix;
            # no old submission format is accepted or transformed.
            text=str(error);recorded=event.get('output') or ''
            if not recorded or not text.startswith(recorded):return None
            return {'message_id':message['id'],'trace_sha256':digest(trace),
                    'submission_id':operation,'error':text, **correction_context(error)}
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
        connection.execute('BEGIN IMMEDIATE')
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
    if repair.get('approval'):
        purpose = ('原结果尚未交给审批人。只补齐审批说明，不重做原任务，不代替用户作决定，也不重新执行外部操作。'
            '根据本轮已核实的结果、汇报和原审批要求，说明需要用户决定什么、每个选项会发生什么。'
            '沿原结果补充 approval_request，每个配置的决定对应一个选项。未知的事实请如实说明。\n审批要求：'
            + json.dumps(repair['approval'], ensure_ascii=False))
    elif repair.get('handoff'):
        purpose = ('系统确认下一岗位没有接收到交付。请用本轮已获准的汇报和已有证据核对缺项，'
            '补齐能从原证据确认的内容。不要重做原任务，也不要重新执行上传、发布等外部操作。'
            '如果已有证据表明应退回其他员工，请按你岗位的已配置结果提交。只有确实需要用户独有的资料、'
            '权限或决定时，才提交 needs_human，并说明缺什么、为何需要、用户具体要做什么。'
            '不能从现有证据确认的值不得猜填。\n交接检查：'
            + json.dumps(repair['handoff'], ensure_ascii=False))
    else:
        purpose = ('原回合已停止，正式提交未形成交接回执。'
            '这是一回合提交格式纠正，不是重做原任务。先 read 核对原报告、receipt 和 result_schema，'
            '沿你已形成的专业判断，由你重新提交；不得重新采集、执行业务操作、改稿、派工或代做人工决定。'
            '若原判断不能确认，停止并如实说明；不要补造结论。')
    prompt = (purpose + '\nresult.status、result.summary 是外层字段，全部技能产出放在 result.output 中。'
        '沿原被拒绝的 operation_id='+proof['submission_id']+'。校验提示：'+proof['error']+
        '\n提交结构：'+json.dumps(result_schema(frozen['package'],frozen['pipeline_work']),ensure_ascii=False))
    from runteams_core.pipelines.pipeline_execution_activity import capture
    with capture(core, identifier, frozen):
        status,reason=executor(frozen['work_chat_id'],prompt,core._cancel_event(identifier),
            'employee-work:'+str(identifier))
        return finish_turn(core,identifier,status,reason,expected_visit=frozen['pipeline_visit'])


def rearm_unstarted_correction(core,identifier,*,expected_visit=None):
    """Explicit recovery of a rejected preflight, never an admitted model turn.

    The original Handler persists the user message before starting the model.
    An unchanged, revalidated source message proves this correction never got
    that far. Any new message or unknown native effect keeps the fence closed.
    """
    with core.repository.connect()as connection:
        connection.execute('BEGIN IMMEDIATE')
        row=_row(connection,identifier);frozen=json.loads(row['snapshot_json'])
        repair=frozen.get('pipeline_result_correction')or{}
        if ((expected_visit is not None and frozen['pipeline_visit']!=expected_visit)
                or row['state'] not in ('paused','needs_human','interrupted') or
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


def correction_context(error):
    if isinstance(error, ApprovalBriefMissing):
        return {'approval': error.approval}
    return {'handoff': error.issue} if isinstance(error, HandoffInputRejected) else {}


def _recheck_submission(core, connection, frozen, result):
    result = _result(frozen['package'], frozen['pipeline_work'], result)
    if connection is not None:
        try:
            _check_downstream(core, connection, frozen, result)
        except ContractError as error:
            # Host/configuration failures are outside this employee's repair.
            if isinstance(error, (HandoffInputRejected, ApprovalBriefMissing)):
                raise


def _check_downstream(core, connection, frozen, result):
    definition = frozen['pipeline_work']['asset']['pipeline']; key = frozen['pipeline_work']['position_key']
    edge = None if result['output'].get('quality_feedback') else core._matching_edge(definition, key, result)
    if (edge and definition.get('routing_policy') == PIPELINE_STATUS_FIRST and not result.get('approval_request')
            and any(p['key'] == edge['to'] and p['kind'] == 'approval' for p in definition['positions'])):
        raise ApprovalBriefMissing(edge['to'], approval_decisions(definition, edge['to']))
    if edge and edge['to'] in {p['key'] for p in definition['positions'] if p['kind'] == 'employee'}:
        bundle = control.bundle_for_work(core, connection, frozen)
        role = bundle['roles'][edge['to']]
        # A returning visit invalidates its previous output and later consumers.
        prospective = copy.deepcopy(frozen)
        _lineage(connection, prospective, edge['to'], frozen.get('employee_run_id'), result)
        try:
            extra = {'id': frozen['employee_run_id'], 'position_key': key, 'state': result['status'], 'output_json': result}
            payload_for(core, connection, prospective, role, extra if frozen['employee_run_id'] in prospective['pipeline_lineage'] else None)
        except work.StageInputError as error:
            issue = {'from': key, 'to': edge['to'], **_input_issue(definition, error, key)}
            names = {position['key']:position['name'] for position in definition['positions']}
            owners = '用户' if issue['requires_user_input_or_authorization'] else '、'.join(
                names[owner] for owner in issue['responsible_positions'] if owner in names)
            raise HandoffInputRejected(issue, owners) from error


def _check_human_dependency(context, result):
    from runteams_core.work.work_ledger import WorkLedger
    graph = (context.get('asset') or {}).get('pipeline', {})
    edge = None if result['output'].get('quality_feedback') else WorkLedger._matching_edge(
        graph, context.get('position_key'), result)
    request = result.get('human_request')
    employee_handoff = edge and any(position['key'] == edge['to'] and position['kind'] == 'employee'
                                    for position in graph['positions'])
    if request:
        if employee_handoff:
            raise ContractError('当前结果已有员工接续路线。请提交交接，去掉人工提问。')
        blocker = request.get('blocker')
        if not blocker:
            raise ContractError('请先继续完成员工能做的工作。确实需要人工时，在 human_request.blocker 中说明具体缺少的信息、授权或决定，以及你已做过哪些核对。')
        if blocker['kind'] == 'information' and all(option['input_mode'] == 'none' for option in request['options']):
            raise ContractError('缺少信息时，至少一个选项要让用户补充所需信息。')
    elif not employee_handoff and not result.get('setup_required') and (
            result['status'] == 'needs_human' or edge and edge['to'] == PIPELINE_WAIT_FOR_INPUT
            and not edge.get('configuration_fields')):
        raise ContractError('只有确实需要人工时才等待用户。请提交带 blocker 的 human_request，或继续工作并按已配置的路线提交。')


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
    feedback = result.get('human_request')
    if feedback:
        _require_input_contract(feedback)
    elif human_request({'result': result}):
        graph = (frozen['pipeline_work'].get('asset') or {}).get('pipeline', {})
        edge = core._matching_edge(graph, frozen['pipeline_work'].get('position_key'), result) if graph else None
        if result['status'] in ('blocked', 'needs_human') or edge and edge['to'] == PIPELINE_WAIT_FOR_INPUT:
            raise ContractError('请将反馈问题和选项放在 result.human_request，并为每个选项声明 input_mode。')
    _check_human_dependency(frozen['pipeline_work'], result)
    _check_downstream(core, connection, frozen, result)
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
            current = frozen['pipeline_work']
            # Returning to a position drops its stale outputs, but the current
            # sender can explicitly hand new values back to that position.
            handoff = run_id and result and result['status'] == 'completed' and _declared_handoff(
                current['asset']['pipeline'], current['position_key'], target, result['output'])
            lineage = lineage[:index]
            if handoff and run_id not in lineage:
                lineage.append(run_id)
            break
    frozen['pipeline_lineage'] = lineage


def signing_setup(frozen):
    waiting = frozen.get('pipeline_waiting') or {}
    context = frozen.get('pipeline_work') or {}
    if waiting.get('kind') != 'result' or not context or waiting.get('position_key') != context['position_key']:
        return None
    result = waiting.get('result') or {}
    if result.get('status') not in ('blocked', 'needs_human'):
        return None
    # Older submissions carry the exact requirement in the recorded issues.
    legacy = any(isinstance(issue, str) and '项目未配置 Apple 开发团队' in issue
                 and '开发证书' in issue and '描述文件' in issue for issue in result.get('issues') or ())
    if result.get('setup_required') != APPLE_DEVICE_SIGNING and not legacy:
        return None
    _, member = work._position(context['asset'], context['position_key'])
    from runteams_core.pipelines.pipeline_dependency_contracts import selector
    return {'employee_source': selector(member)}


def resume_verified_signing(core, connection, row, frozen, evidence):
    """Resume the same position with task-local configuration and verified evidence."""
    from runteams_core.pipelines.pipeline_context import current as pipeline_context

    context = frozen['pipeline_work']
    configuration = pipeline_context().member_configuration(context['reference'], frozen['package']).snapshot(
        task_values={'apple_team_id': evidence['team_id']})
    waiting = frozen['pipeline_waiting']
    frozen['pipeline_signing_verification'] = {**evidence, 'position_key': waiting['position_key']}
    frozen['pipeline_response'] = (
        f"协助对话已验证 iPhone 开发签名，并在 {evidence['device_model']} 上核对到 "
        f"{evidence['bundle_id']} {evidence['version']}（构建 {evidence['build']}）已安装并运行。"
        "请沿当前岗位继续，引用已核验的结果。")
    _move(core, connection, row, frozen, waiting['position_key'], waiting['result'],
          waiting['source_run_id'], configuration=configuration)
    return connection.execute('SELECT state FROM workflow_runs WHERE id=?', (row['id'],)).fetchone()[0]


def apply_wait_configuration_fields(waiting, fields):
    request = human_request(waiting)
    # Legacy choices previously took the place of the route's configuration form.
    if fields and (not request or has_input_contract(request)):
        waiting['configuration_fields'] = list(fields)
    else:
        waiting.pop('configuration_fields', None)


def wait_for_input(frozen, position, result, run_id, configuration_fields=()):
    waiting = {'kind': 'result', 'state': 'needs_human', 'position_key': position,
            'source_run_id': run_id, 'result': {**result, 'status': 'needs_human'},
            'configuration_before': digest((frozen.get('pipeline_input') or {}).get('parameters', {}))}
    apply_wait_configuration_fields(waiting, configuration_fields)
    return waiting


def can_continue_with_configuration(frozen, waiting):
    before = waiting.get('configuration_before')
    return bool(before and before != digest((frozen.get('pipeline_input') or {}).get('parameters', {})))


def _move(core, connection, row, frozen, target, result, run_id=None, *, configuration=None):
    definition = frozen['pipeline_work']['asset']['pipeline']
    _lineage(connection, frozen, target, run_id, result)
    states = {s['key']: s['kind'] for s in definition.get('states', [])}
    if target in states:
        if (states[target] == 'pool' and result['status'] == 'needs_human'
                and definition.get('routing_policy') == PIPELINE_STATUS_FIRST):
            frozen['pipeline_waiting'] = {'kind': 'result', 'state': 'needs_human',
                'position_key': frozen['pipeline_work']['position_key'],
                'source_run_id': run_id, 'result': result}
            _save(core, connection, row, frozen, 'needs_human', target)
            return
        _save(core, connection, row, frozen, 'canceled' if states[target]=='dropped' else 'blocked' if states[target]=='pool' else 'completed', target)
        return
    position = next(p for p in definition['positions'] if p['key'] == target)
    if position['kind'] == 'approval':
        frozen['pipeline_waiting'] = {'kind':'approval','position_key': target, 'source_run_id': run_id}
        if result.get('approval_request'):
            frozen['pipeline_waiting']['approval_request'] = result['approval_request']
        _save(core, connection, row, frozen, 'needs_approval', target)
        core.repository.event('workflow_run:' + str(row['id']), 'workflow.approval_requested',
            {'position_key': target, 'prompt': position.get('prompt') or '请确认是否继续'}, connection=connection)
        return
    bundle = control.bundle_for_work(core, connection, frozen); role = bundle['roles'][target]
    signing = frozen.get('pipeline_signing_verification')
    if signing and signing['bundle_id'] != frozen.get('pipeline_input', {}).get('parameters', {}).get('bundle_id'):
        signing = None
    configured = role['configuration']
    if (configuration is None and signing and signing['position_key'] == target and configured
            and 'apple_team_id' in configured['states']
            and configured['values'].get('apple_team_id') in (None, '', signing['team_id'])):
        configuration = copy.deepcopy(configured)
        configuration['values']['apple_team_id'] = signing['team_id']
        configuration['states']['apple_team_id'] = 'configured'
    next_frozen = work.stage_snapshot(role['package'], role['context'],
                                      role['configuration'] if configuration is None else configuration)
    next_frozen['language_policy'] = copy.deepcopy(frozen.get('language_policy', {'communication_language': 'zh-CN'}))
    if signing:
        next_frozen['pipeline_signing_verification'] = signing
    next_frozen.update(pipeline_history=archive(frozen), pipeline_visit=frozen['pipeline_visit'] + 1,
        pipeline_generation=frozen['pipeline_generation'], pipeline_input=frozen['pipeline_input'],
        pipeline_lineage=frozen['pipeline_lineage'])
    for key in ('rerun', 'initial_pipeline_input', 'queued_pipeline_input', 'repeat_order', 'schedule_origin', 'manual_order'):
        if key in frozen:
            next_frozen[key] = frozen[key]
    if frozen.get('pipeline_execution'):next_frozen['pipeline_execution'] = frozen['pipeline_execution']
    next_frozen['pipeline_feedback'] = {'from': row['cursor_key'],
        'employee_run_id': run_id, 'summary': result['summary'], 'issues': result['issues'],
        'route': result['output'].get('route', '')}
    if frozen.get('pipeline_response') and (target == row['cursor_key'] or
            (result['status'] == 'needs_human' and target == frozen['pipeline_work']['position_key'])):
        next_frozen['pipeline_response'] = frozen['pipeline_response']
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


def _follow_edge(core, connection, row, frozen, edge, result, run_id):
    definition = frozen['pipeline_work']['asset']['pipeline']
    target = edge['to']
    if target == PIPELINE_COMPLETE_HERE and definition.get('routing_policy') == PIPELINE_STATUS_FIRST:
        _lineage(connection, frozen, target, run_id, result)
        _save(core, connection, row, frozen, 'completed')
        core.repository.event('workflow_run:' + str(row['id']), 'workflow.completed',
            {'position_key': row['cursor_key'], 'employee_run_id': run_id}, connection=connection)
    else:
        core._route_workflow(row['id'], edge, run_id)
        _move(core, connection, row, frozen, target, result, run_id)


def launch_failure(connection, row, frozen):
    if row['state'] not in ('needs_human', 'blocked') or any(frozen.get(key) for key in (
            'employee_run_id', 'send_admitted', 'pipeline_waiting', 'pipeline_setup_required',
            'pipeline_handoff', 'pipeline_submission', 'pipeline_unresolved', 'pipeline_recovery_pending',
            'pipeline_result_correction', 'pipeline_applied_result')):
        return None
    events = connection.execute(
        "SELECT type,data_json FROM events WHERE stream=? AND type IN "
        "('workflow.claimed','workflow.needs_human','workflow.blocked','workflow.pipeline_updated','workflow.launch_retried') "
        "ORDER BY id DESC LIMIT 2", ('workflow_run:' + str(row['id']),)).fetchall()
    if len(events) != 2 or events[0]['type'] not in ('workflow.needs_human','workflow.blocked') or events[1]['type'] != 'workflow.claimed':
        return None
    event = json.loads(events[0]['data_json'])
    if event.get('position_key') == row['cursor_key'] and event.get('reason'):
        return event['reason']
    return None


def retry_mode(state, cursor, frozen, positions, *, active=False, launch_error=None):
    key = (frozen.get('pipeline_work') or {}).get('position_key')
    if (not key or cursor != key or key not in positions
            or active or (frozen.get('pipeline_execution') or {}).get('active')
            or frozen.get('pipeline_recovery_pending')
            or frozen.get('pipeline_submission') and not frozen.get('pipeline_applied_result')):
        return None
    if launch_error:
        return 'launch'
    if state not in ('failed', 'interrupted'):
        return None
    if frozen.get('pipeline_unresolved') or frozen.get('send_admitted') and not frozen.get('pipeline_applied_result'):
        return 'verify'
    return 'retry'


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
        if row['state'] == 'canceled':
            if frozen.get('pipeline_execution'):
                frozen['pipeline_execution']['active'] = False
            if frozen.get('send_admitted') and not frozen.get('pipeline_applied_result'):
                frozen['pipeline_unresolved'] = True
            frozen.pop('pipeline_recovery_pending', None)
            frozen.pop('pipeline_program_error', None)
            _save(core, connection, row, frozen, 'canceled')
            return 'canceled'
        if frozen.get('pipeline_applied_result'):
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
            elif status == 'blocked' and not frozen.get('employee_run_id') and not frozen.get('pipeline_setup_required'):
                state = 'blocked'
        if frozen.get('employee_run_id'):
            connection.execute('UPDATE employee_runs SET state=?,output_json=?,updated_at=? WHERE id=?',
                (state, canonical({**result, 'transport_status': status,'report_references':(submitted or {}).get('reports',[])}).decode(), utc_now(), frozen['employee_run_id']))
        definition = frozen['pipeline_work']['asset']['pipeline']; key = frozen['pipeline_work']['position_key']
        edge = core._matching_edge(definition, key, result) if submitted and not result['output'].get('quality_feedback') else None
        if edge and edge['to'] == PIPELINE_WAIT_FOR_INPUT and definition.get('routing_policy') == PIPELINE_STATUS_FIRST:
            frozen['pipeline_waiting'] = wait_for_input(
                frozen, key, result, frozen['employee_run_id'], edge.get('configuration_fields', ()))
            _save(core, connection, row, frozen, 'needs_human', key)
            core.repository.event('workflow_run:' + str(identifier), 'workflow.needs_human',
                {'position_key': key, 'employee_run_id': frozen['employee_run_id']}, connection=connection)
        elif edge:
            _follow_edge(core, connection, row, frozen, edge, result, frozen['employee_run_id'])
        else:
            if submitted and state == 'completed':state = 'blocked';reason = '岗位已提交结果，但没有匹配的流转连线；请核对智能体团队定义。'
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


def _export_report(core, chat_id, document):
    from runteams_core.documents.document_export import export_document
    from runteams_core.employees.employee_workspaces import workspace
    from runteams_core.foundation.durable_files import move
    from runteams_core.foundation.regular_files import storage_path

    raw, _, _ = export_document(core, document)
    managed = storage_path(workspace(chat_id)) / '.runteams'
    directory = managed / 'handoff-reports'
    for path in (managed, directory):
        if path.is_symlink():
            raise ContractError('工作汇报副本目录无效。')
        path.mkdir(mode=0o700, exist_ok=True)
    checksum = hashlib.sha256(raw).hexdigest()
    target = directory / (str(document['id']) + '-' + checksum + '.json')
    if not target.exists() and not target.is_symlink():
        stream = tempfile.NamedTemporaryFile(dir=directory, delete=False)
        temporary = Path(stream.name)
        try:
            with stream:
                stream.write(raw)
            temporary.chmod(0o400)
            try:
                move(temporary, target)
            except FileExistsError:
                pass  # Another reader published the same report. Verify its bytes below.
        finally:
            if temporary.exists():
                temporary.chmod(0o600)
                temporary.unlink()
    if target.is_symlink():
        raise ContractError('工作汇报副本不能是链接。')
    with target.open('rb') as stream:
        if hashlib.file_digest(stream, 'sha256').hexdigest() != checksum:
            raise ContractError('已有工作汇报副本已变化。')
    return {'path': str(target), 'sha256': checksum, 'access': 'read-copy'}


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
    if not (session or {}).get('context', {}).get('pipeline_work'):raise PermissionError('此工具仅用于智能体团队当前岗位。')
    identifier = session['context']['employee_work']['workflow_id'];core = device_work_service()
    operation = arguments.get('operation')
    transaction = core.repository.read_snapshot if operation in ('read', 'read_report', 'export_report') else core.repository.connect
    with core.repository.audit_context(actor_id=principal(scope), source='agent_tool'),transaction() as connection:
        row = _row(connection, identifier);frozen = json.loads(row['snapshot_json'])
        if frozen.get('work_chat_id') != cid or row['state'] != 'running' or not (frozen.get('pipeline_execution') or {}).get('active'):
            raise PermissionError('当前岗位已经交接或停止。')
        if operation == 'submit' and set(arguments) == {'operation', 'operation_id', 'result'}:
            if len(canonical(arguments)) > 96 * 1024:raise ContractError('岗位结果过大，请使用正式记录引用。')
            return _submission(core, connection, row, frozen, arguments['operation_id'], arguments['result'])
        from runteams_core.work.work_reports import _agent_document
        reports = _reports(core,connection,frozen)
        if operation in ('read_report', 'export_report') and set(arguments) == {'operation', 'report_id'}:
            if type(arguments['report_id']) is not int or not any(r['id'] == arguments['report_id'] for r in reports):raise PermissionError('这份汇报不属于当前获准交接的工作。')
            reference=next(r for r in reports if r['id']==arguments['report_id'])
            document=core.historical_document_detail(reference['artifact_id'])
            if not document or document['revision']!=reference['revision'] or hashlib.sha256(document['content'].encode()).hexdigest()!=reference['sha256']:
                raise ContractError('原交接汇报版本无法确认，请核对原记录。')
            if operation == 'export_report':
                if document.get('content_model') != 'rich-document':
                    raise ContractError('请选择带有原生附件的工作汇报。')
                return {'reference': reference, 'resource': _export_report(core, cid, document)}
            return {'document': _agent_document(document), 'read_only': True}
        if operation != 'read' or set(arguments) != {'operation'}:raise ContractError('请选择读取交接、读取汇报或提交结果。')
        role = {'context': frozen['pipeline_work'], 'package': frozen['package']}
        payload = payload_for(core, connection, frozen, role)
        stage = payload['context']['pipeline_stage']
        add_approval_history(connection, identifier, role['context'], stage)
        return {'position_key': frozen['pipeline_work']['position_key'], 'parameters': payload['parameters'],
            'stage': stage, 'reports': reports,
            'output_schema': (declared(frozen['package'], payload['skill_key']) or {}).get('output_schema', {'type': 'object'}),
            'result_schema': result_schema(frozen['package'],frozen['pipeline_work']),
            'receipt': (frozen.get('pipeline_submission') or {}).get('receipt')}


def _command_request(data):
    fields={'operation_id','reference','workflow_id','expected_visit','action'}
    if not isinstance(data,dict) or data.get('action') not in ('decide','respond','recover','input','retry','resume_setup','suggest_responses','suggest_approval'):
        raise ContractError('请选择处理人工决定、回答问题或核对原工作。')
    extra={'decide':{'decision','note'},'respond':{'response'},'recover':set(),'input':{'parameters'},
           'retry':{'verified'},'resume_setup':set(),'suggest_responses':{'human_request'},
           'suggest_approval':{'approval_request'}}[data['action']]
    if data['action']=='respond' and 'choice' in data:
        extra.add('choice')
    if set(data)!=fields|extra:raise ContractError('工作恢复参数无效。')
    try:
        if str(uuid.UUID(data['operation_id']))!=data['operation_id']:raise ValueError()
    except (ValueError,TypeError,AttributeError):raise ContractError('请沿原工作操作编号恢复。') from None
    if type(data['workflow_id']) is not int or type(data['expected_visit']) is not int or min(data['workflow_id'],data['expected_visit'])<1:
        raise ContractError('原工作或岗位访问编号无效。')
    if data['action']=='input':
        if not isinstance(data['parameters'],dict) or len(canonical(data['parameters']))>65536:raise ContractError('任务输入格式无效。')
    if data['action']=='retry' and type(data['verified']) is not bool:
        raise ContractError('请确认是否已核对原结果。')
    for key in extra-{'parameters','verified','human_request','approval_request'}:
        if not isinstance(data[key],str) or len(data[key])>4000 or key not in ('note','response') and not data[key].strip():
            raise ContractError('请填写有效的决定或回答。')
    if data['action']=='respond' and len(data.get('choice', '')) > 100:
        raise ContractError('请选择一项或填写自己的回答。')
    if data['action']=='suggest_responses':
        _human_request(data['human_request'])
    if data['action']=='suggest_approval':
        _human_request(data['approval_request'], schema=APPROVAL_REQUEST_SCHEMA)
    return {**copy.deepcopy(data),'reference':pipeline_references.checked_reference(data['reference'])}


def _prepared_recovery(core,request,active_ids,read_only,guard):
    if read_only or request['action']!='recover':return None
    with core.repository.connect() as connection:
        if connection.execute("SELECT 1 FROM events WHERE stream=? AND type='pipeline.flow_committed'",
                ('source-pipeline-flow:'+request['operation_id'],)).fetchone():return None
        row=_row(connection,request['workflow_id']);frozen=json.loads(row['snapshot_json'])
        if not frozen.get('pipeline_setup_required'):return None
        if guard is not None:guard(row,frozen)
        if frozen['pipeline_work']['reference']!=request['reference']:
            raise PermissionError('工作不属于这个智能体团队。')
        if frozen['pipeline_visit']!=request['expected_visit']:
            raise WorkflowVisitChanged('工作已流转，请查看当前进度。')
        if (row['state'] not in ('blocked','needs_human') or request['workflow_id'] in active_ids
                or (frozen.get('pipeline_execution') or {}).get('active')
                or control.read(core,request['reference'],connection)['status']!='running'):
            raise ContractError('原岗位尚未停止或智能体团队已暂停，请先核对运行状态。')
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


def _execution_needs_review(row, frozen, visit):
    return (frozen['pipeline_visit'] == visit
            and row['state'] in ('blocked', 'needs_human', 'interrupted', 'paused', 'failed')
            and frozen.get('send_admitted') and not frozen.get('pipeline_applied_result')
            and not (frozen.get('pipeline_execution') or {}).get('active'))


def _review_execution(core, identifier, visit):
    """Settle existing evidence or record that the result is still unknown."""
    with core.repository.connect() as connection:
        connection.execute('BEGIN IMMEDIATE')
        row = _row(connection, identifier)
        frozen = json.loads(row['snapshot_json'])
        if not _execution_needs_review(row, frozen, visit):
            return
        has_result = bool(frozen.get('pipeline_submission') or frozen.get('pipeline_recovery_pending'))
        if not has_result and _queue_result_correction(core, connection, row, frozen):
            return
    if has_result:
        finish_turn(core, identifier, 'interrupted', expected_visit=visit)
        return
    if rearm_unstarted_correction(core, identifier, expected_visit=visit):
        return
    from runteams_core.pipelines.pipeline_context import current as pipeline_context
    if pipeline_context().reconcile_result(core, identifier, expected_visit=visit):
        return
    with core.repository.connect() as connection:
        connection.execute('BEGIN IMMEDIATE')
        row = _row(connection, identifier)
        frozen = json.loads(row['snapshot_json'])
        if (not _execution_needs_review(row, frozen, visit) or frozen.get('pipeline_submission')
                or frozen.get('pipeline_recovery_pending')):
            return
        stream = 'workflow_run:' + str(identifier)
        if row['state']=='needs_human' and not frozen.get('pipeline_waiting'):
            _save(core, connection, row, frozen, 'interrupted')
            current = _row(connection, identifier)['state']
            core.repository.event(stream, 'workflow.'+current, {'position_key': row['cursor_key']}, connection=connection)
        if not connection.execute(
                "SELECT 1 FROM events WHERE stream=? AND type='workflow.result_checked' "
                "AND json_extract(data_json,'$.visit')=? LIMIT 1", (stream, visit)).fetchone():
            core.repository.event(stream, 'workflow.result_checked', {'visit': visit}, connection=connection)


def command(core,data,active_ids=(),*,read_only=False,guard=None,materials=None,chat_fingerprint=None):
    core._actor();request=_command_request(data);identifier=request['workflow_id'];key=request['operation_id']
    prepared=_prepared_recovery(core,request,active_ids,read_only,guard)
    with core.repository.connect() as connection:
        if not read_only and (guard is not None or request['action'] in ('retry','resume_setup','decide','suggest_approval')):
            connection.execute('BEGIN IMMEDIATE')
        row=_row(connection,identifier);frozen=json.loads(row['snapshot_json'])
        if (frozen.get('pipeline_work') or {}).get('reference')!=request['reference']:raise PermissionError('工作不属于这个智能体团队。')
        event=connection.execute("SELECT data_json FROM events WHERE stream=? AND type='pipeline.flow_committed' LIMIT 1",('source-pipeline-flow:'+key,)).fetchone()
        if event:
            value=json.loads(event[0])
            if value['request_sha256']!=digest(request):raise ContractError('原操作编号已用于其他内容。')
            receipt=value['receipt']
        elif read_only:
            return {'operation_id':key,'status':'unknown'}
        else:
            core.repository.storage.assert_executable(identifier)
            # A final approval can close the task without advancing the visit.
            closed_approval = request['action'] == 'decide' and row['state'] in ('completed', 'canceled')
            if closed_approval or frozen['pipeline_visit'] != request['expected_visit']:
                raise WorkflowVisitChanged('工作已流转，请查看当前进度。')
            if identifier in active_ids:raise ContractError('原岗位仍在执行，请等待收尾，不会并发恢复。')
            if guard is not None:guard(row,frozen)
            saved=control.read(core,request['reference'],connection)
            if (frozen.get('pipeline_execution') or {}).get('active'):
                raise ContractError('原执行尚未确认停止，请等待系统核对，不会并发恢复。')
            if request['action']!='recover' and saved['status']!='running':
                raise ContractError('智能体团队已暂停或原岗位尚未收尾。')
            waiting=frozen.get('pipeline_waiting') or {};action=request['action']
            if action=='recover' and row['state']=='running':raise ContractError('原工作仍在执行，请等待执行器确认停止。')
            if action=='retry':
                error = launch_failure(connection, row, frozen)
                mode = retry_mode(row['state'],row['cursor_key'],frozen,saved['bundle']['roles'],launch_error=error)
                if not mode or (mode=='verify' and not request['verified']):
                    raise ContractError('请先核对原执行及外部结果，再从当前岗位重试。')
                if mode == 'launch':
                    _save(core, connection, row, frozen, 'ready')
                    core.repository.event('workflow_run:'+str(identifier), 'workflow.launch_retried',
                        {'position_key':row['cursor_key'],'visit':frozen['pipeline_visit']}, connection=connection)
                else:
                    run_id = frozen.get('employee_run_id')
                    attempt = connection.execute('SELECT output_json FROM employee_runs WHERE id=?', (run_id,)).fetchone()
                    result = json.loads(attempt[0]) if attempt else {}
                    _move(core,connection,row,frozen,row['cursor_key'],{
                        'status':'failed','summary':result.get('summary') or '从失败岗位继续。请先核对原项目中已完成的工作，再完成交接。',
                        'issues':result.get('issues',[]),'output':{}},run_id)
                    core.repository.event('workflow_run:'+str(identifier),'workflow.stage_retried',
                        {'position_key':row['cursor_key'],'previous_visit':request['expected_visit'],
                         'verified':request['verified']},connection=connection)
            elif action=='suggest_approval':
                if (row['state'] != 'needs_approval' or waiting.get('kind') != 'approval'
                        or waiting.get('position_key') != row['cursor_key'] or not waiting.get('source_run_id')
                        or waiting.get('approval_request')):
                    raise ContractError('当前工作没有可补充选项的原审批环节。')
                waiting['approval_request'] = _approval_request(
                    request['approval_request'], frozen['pipeline_work']['asset']['pipeline'], row['cursor_key'])
                _save(core, connection, row, frozen, row['state'])
            elif action=='decide':
                if row['state']!='needs_approval' or waiting.get('kind')!='approval':raise ContractError('当前工作没有待处理的人工决定。')
                decision=request['decision'].strip()
                result={'status':'completed','summary':request['note'],'output':{'route':decision},'issues':[],'artifacts':[]}
                definition = frozen['pipeline_work']['asset']['pipeline']
                edge=core._matching_edge(definition,row['cursor_key'],{'status':decision,'output':{'route':decision}})
                if not edge:raise ContractError('该决定没有配置流转连线，请先核对智能体团队。')
                core.repository.event('workflow_run:'+str(identifier),'workflow.approval_decided',
                    {'position_key':row['cursor_key'],'decision':decision,'note':request['note']},connection=connection)
                frozen.pop('pipeline_waiting',None)
                _follow_edge(core, connection, row, frozen, edge, result, waiting.get('source_run_id'))
            elif action=='resume_setup':
                if row['state'] not in ('blocked', 'needs_human') or not signing_setup(frozen):
                    raise ContractError('当前岗位没有待补齐的真机签名配置。')
                configuration = control.member_configuration_snapshot(frozen['package'], frozen['pipeline_work'])
                team_id = (configuration or {}).get('values', {}).get('apple_team_id')
                if not isinstance(team_id, str) or not team_id.strip():
                    raise ContractError('请先保存 Apple Team ID，再继续验证真机签名。')
                position_key = waiting['position_key']
                frozen.pop('pipeline_waiting')
                frozen['pipeline_response'] = '用户已确认签名材料准备就绪。请先验证本机开发证书和描述文件能否为这台 iPhone 签名并安装。'
                _move(core, connection, row, frozen, position_key, waiting['result'], waiting.get('source_run_id'),
                      configuration=configuration)
                core.repository.event('workflow_run:'+str(identifier),'workflow.signing_setup_confirmed',
                    {'position_key': position_key}, connection=connection)
            elif action in ('respond','suggest_responses'):
                if row['state'] not in ('blocked','needs_human') or waiting.get('kind')!='result' or waiting['result']['status'] not in ('blocked','needs_human'):
                    raise ContractError('只有已确认的问题等待才能接续回答；未知发送不能重发。')
                if signing_setup(frozen):
                    raise ContractError('请先完成真机签名配置，再使用签名验证入口继续。')
                position_key = waiting['position_key']
                existing = feedback_request(frozen)
                if action=='suggest_responses':
                    if existing or waiting.get('configuration_fields') or not waiting.get('source_run_id'):
                        raise ContractError('当前阻塞已附有反馈选项，或原执行尚未确认。')
                    suggested = _human_request(request['human_request'])
                    _require_input_contract(suggested)
                    for item in suggested['options']:
                        _feedback_fields(frozen['pipeline_work'], item.get('configuration_fields', []))
                    waiting['human_request'] = suggested
                    _save(core,connection,row,frozen,row['state'])
                    core.repository.event('workflow_run:'+str(identifier),'workflow.feedback_options_suggested',
                        {'position_key':position_key,'source_run_id':waiting['source_run_id']},connection=connection)
                else:
                    response = request['response'].strip()
                    choice = request.get('choice','').strip()
                    option_fields = []
                    if has_input_contract(existing) and not choice:
                        raise ContractError('请选择一项，并按该选项的要求填写信息。')
                    if choice:
                        if not existing or not any(item['label']==choice for item in existing['options']):
                            raise ContractError('所选选项已失效，请重新查看当前问题。')
                        option = next(item for item in existing['options'] if item['label'] == choice)
                        mode = option.get('input_mode')
                        if mode in TEXT_INPUT_MODES and not response:
                            raise ContractError('请填写：' + option['response_prompt'])
                        if mode is not None and mode not in TEXT_INPUT_MODES and response:
                            raise ContractError('这个选项不需要填写文字说明。')
                        option_fields = option.get('configuration_fields', [])
                        response = '选择：'+choice+('\n补充：'+response if response else '')
                    fields = dict.fromkeys([*(waiting.get('configuration_fields') or []), *option_fields])
                    if fields:
                        values = (frozen.get('pipeline_input') or {}).get('parameters', {})
                        if any(values.get(key) in (None, '', []) or
                               isinstance(values[key], str) and not values[key].strip() for key in fields):
                            raise ContractError('请填写本次必需的配置，再继续。')
                        confirmation = '用户已确认本次必需的任务配置，请核对配置并继续本岗位工作。'
                        response = response + '\n' + confirmation if response else confirmation
                    elif not response:
                        if materials is None and not can_continue_with_configuration(frozen, waiting):
                            raise ContractError('请先补充信息或更新任务配置，再继续。')
                        response = ('用户补充了本次工作的资料，请核对任务输入。' if materials else
                                    '用户已更新任务配置，请核对当前配置并继续本岗位工作。')
                    if materials is not None:materials(row,frozen)
                    frozen['pipeline_response']=response
                    frozen.pop('pipeline_waiting',None)
                    _move(core,connection,row,frozen,position_key,waiting['result'],waiting.get('source_run_id'))
                    core.repository.event('workflow_run:'+str(identifier),'workflow.human_responded',
                        {'position_key':position_key,**({'choice':choice} if choice else {})},connection=connection)
            elif action=='input':
                issue=frozen.get('pipeline_handoff') or {}
                if row['state']!='blocked' or not issue.get('requires_user_input_or_authorization') or frozen.get('send_admitted'):
                    raise ContractError('当前工作没有可补齐的已确认任务输入；未知发送不能重发。')
                declarations=frozen['pipeline_work']['asset']['pipeline'].get('parameters',[])
                visible=[p for p in declarations if p.get('source')=='user' and p.get('type')!='secret' and (not p.get('visible_to') or row['cursor_key'] in p['visible_to'])]
                allowed={p['key'] for p in visible if p.get('display')!='setup'}
                configured_issue=any(p.get('display')=='setup' and p['key'] in issue.get('fields',[]) for p in visible)
                if (not request['parameters'] and not configured_issue and materials is None) or set(request['parameters'])-allowed:
                    raise ContractError('只能补齐已声明的用户任务输入，不能改写员工产出或资料授权。')
                frozen['pipeline_input']['parameters']={**frozen['pipeline_input'].get('parameters',{}),**copy.deepcopy(request['parameters'])}
                if materials is not None:materials(row,frozen)
                role=control.bundle_for_work(core, connection, frozen)['roles'][row['cursor_key']]
                payload_for(core,connection,frozen,role)
                _move(core,connection,row,frozen,row['cursor_key'],{'status':'completed','summary':'使用者补齐了任务输入。','output':{},'issues':[]})
                core.repository.event('workflow_run:'+str(identifier),'workflow.input_supplied',{'position_key':row['cursor_key'],'fields':sorted(request['parameters'])},connection=connection)
            else:
                if row['state'] in control.TERMINAL and not _execution_needs_review(row, frozen, request['expected_visit']):
                    raise ContractError('已结束的工作不重新运行。')
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
            audit = {'request_sha256': digest(request), 'receipt': receipt}
            if chat_fingerprint is not None:
                audit['chat_request_sha256'] = chat_fingerprint
            core.repository.event('source-pipeline-flow:'+key,'pipeline.flow_committed',audit,connection=connection)
    if not read_only:
        if request['action']=='recover':
            try:
                _review_execution(core, identifier, request['expected_visit'])
            except (ContractError, RuntimeError, OSError) as error:
                raise work.WorkAdmissionUnknown(key) from error
        control.settle_pause(core,request['reference'])
    try:return {'operation_id':key,'status':'committed','receipt':receipt,'result':work.work(core,request['reference'],identifier)}
    except PermissionError:raise
    except Exception as error:raise work.WorkAdmissionUnknown(key) from error
