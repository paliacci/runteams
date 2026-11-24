"""Continue a specific employee work order from its owning interactive chat."""
from dataclasses import dataclass
import json
import logging
import uuid

from runteams_core.authoring.creator_contracts import canonical, digest
from runteams_core.employees import employee_binding, employee_references, employee_work_contracts
from runteams_core.foundation.contracts import ContractError
from runteams_core.foundation.identity.work_identity import principal
from runteams_core.storage import device_data, product_store
from runteams_core.storage.repository import utc_now

TOOL = 'runteams_follow_up_employee_work'
DESCRIPTION = (
    'List pending orders (use next_before_id for more) or inspect an exact order, its known reason and supported actions. '
    'Use continue_work to add explicit information or current uploaded attachments and continue the same order. '
    'Use retry only when a previous send did not start. Before acting, inspect the exact order and revision, '
    'copy the current user’s instruction verbatim as intent, and only select attachments from this turn. '
    'Never recreate a work order or resend an unknown execution. Use receipt if the original response was lost.'
)
GUIDANCE = (
    '\n\n# 跟进当前员工的原工单\n'
    '用户点名原工单补资料、续办或重试时，使用 runteams_follow_up_employee_work。先 list 查找并 inspect '
    '核对状态、原因和可用动作。若同名或有歧义，请询问。用户只问状态时只读。'
    '从本轮原话引用明确指令为 intent；补传附件只使用本轮收到的实际编号。'
    '确定未发出的工作可以 retry，已有明确阻塞可按原工作对话 continue_work。'
    '收到未知结果时查询 receipt 或请用户核对；不可把未知结果或旧历史作为重发授权。'
)
_MUTATIONS = ('continue_work', 'retry')
INPUT_SCHEMA = {'type': 'object', 'required': ['operation'], 'additionalProperties': False, 'properties': {
    'operation': {'enum': ['list', 'inspect', 'receipt', *_MUTATIONS]},
    'workflow_id': {'type': 'integer', 'minimum': 1, 'maximum': 2**53-1},
    'action': {'enum': list(_MUTATIONS)},
    'limit': {'type': 'integer', 'minimum': 1, 'maximum': 50},
    'before_id': {'type': 'integer', 'minimum': 1, 'maximum': 2**53-1},
    'revision': {'type': 'string', 'pattern': '^[a-f0-9]{64}$'},
    'intent': {'type': 'string', 'minLength': 2, 'maxLength': 4000},
    'response': {'type': 'string', 'minLength': 1, 'maxLength': 4000},
    'attachment_ids': {'type': 'array', 'minItems': 1, 'maxItems': 10, 'uniqueItems': True,
                       'items': {'type': 'string', 'minLength': 1, 'maxLength': 40}},
}}


@dataclass(frozen=True)
class _Turn:
    chat_id: int
    message_id: int
    scope: dict
    reference: dict
    epoch: str
    cancel: object
    wake: object


def _reference(chat_id):
    if not product_store.device_chat(chat_id):
        raise PermissionError('请从员工主对话跟进原工单。')
    session = product_store.get_chat(chat_id, include_messages=False)
    if not session or (session.get('kind') != 'employee_design' and
                       (session.get('kind') != 'general' or session.get('subject_type') != 'employee')):
        raise PermissionError('请从员工主对话跟进原工单。')
    context = session.get('context') or {}
    if any(context.get(key) for key in ('employee_work', 'pipeline_work', 'employee_schedule_operation')):
        raise PermissionError('请从员工主对话跟进原工单。')
    return employee_binding.resolve(session, read_only=True)['reference']


def bind_turn(context, message_id, cancel, wake=None):
    if (type(message_id) is not int or message_id < 1
            or getattr(cancel, 'background_employee_work', False)
            or getattr(cancel, 'background_chat_turn', False)):
        return False
    chat_id = context.get('chat_id')
    if type(chat_id) is not int or chat_id < 1:
        return False
    try:
        scope = device_data.identity()
        if context.get('actor_id') != principal(scope):
            return False
        reference = _reference(chat_id)
        epoch = device_data.epoch(chat_id)
    except (PermissionError, ValueError, OSError):
        return False
    context['employee_followup_turn'] = _Turn(chat_id, message_id, scope, reference, epoch, cancel, wake)
    return True


def _message(turn):
    if turn.cancel is not None and turn.cancel.is_set():
        raise PermissionError('本轮对话已经结束。')
    device_data.check(turn.scope)
    if (device_data.epoch(turn.chat_id) != turn.epoch
            or not employee_references.same(_reference(turn.chat_id), turn.reference)):
        raise PermissionError('当前员工的对话绑定已变化，请重新打开。')
    message = product_store.get_chat_message(turn.chat_id, turn.message_id)
    if not message or message['role'] != 'user':
        raise PermissionError('本轮用户消息已变化，请重新发送。')
    return message


def _belongs(turn, frozen):
    if frozen.get('schema') != employee_work_contracts.SCHEMA or frozen.get('pipeline_work'):
        return False
    try:
        return employee_references.same(frozen.get('employee_reference'), turn.reference)
    except (ValueError, PermissionError):
        return False


_ROWS = ('SELECT w.*,t.title,t.payload_json FROM workflow_runs w '
         'JOIN tasks t ON t.id=w.task_id WHERE t.trashed_at IS NULL ')


def _work(connection, turn, identifier):
    row = connection.execute(_ROWS + 'AND w.id=?', (identifier,)).fetchone()
    frozen = json.loads(row['snapshot_json']) if row else {}
    if not _belongs(turn, frozen):
        raise PermissionError('这项原工单不属于当前员工或已不可访问。')
    return row, frozen


def _revision(row, frozen):
    return digest([row['state'], row['updated_at'], row['payload_json'], frozen])


def _view(connection, row, frozen):
    identifier = row['id']
    latest = connection.execute(
        'SELECT data_json FROM events WHERE stream=? AND type=? ORDER BY id DESC LIMIT 1',
        ('workflow_run:' + str(identifier), 'workflow.' + row['state'])).fetchone()
    reason = json.loads(latest[0]).get('reason', '') if latest else ''
    attempts = connection.execute(
        'SELECT id,attempt,state FROM employee_runs WHERE workflow_run_id=? ORDER BY attempt DESC,id DESC',
        (identifier,)).fetchall()
    actions = []
    if row['state'] in ('needs_human', 'blocked', 'failed') and isinstance(reason, str) and reason:
        if not frozen.get('send_admitted'):
            actions = ['continue_work'] if attempts else ['continue_work', 'retry']
        elif (attempts and attempts[0]['id'] == frozen.get('employee_run_id')
              and attempts[0]['state'] == row['state'] and frozen.get('work_chat_id')):
            actions = ['continue_work']
    return {'workflow_id': identifier, 'task_id': row['task_id'], 'title': row['title'],
            'state': row['state'], 'reason': reason, 'actions': actions, 'work_chat_id': frozen.get('work_chat_id'),
            'attempt_count': len(attempts), 'revision': _revision(row, frozen)}


def _operation(turn, identifier, action):
    return str(uuid.uuid5(uuid.NAMESPACE_URL,
                          f'runteams-employee-followup:{turn.epoch}:{turn.chat_id}:{turn.message_id}:{identifier}:{action}'))


def _receipt(connection, operation, fingerprint=None):
    prior = connection.execute(
        "SELECT data_json FROM events WHERE stream=? AND type='employee.followup_queued' LIMIT 1",
        ('employee-followup:' + operation,)).fetchone()
    if prior is None:
        return None
    stored = json.loads(prior[0])
    if fingerprint is not None and stored['sha256'] != fingerprint:
        raise ContractError('本次动作已提交，请核对原回执。')
    return stored['receipt']


def _change(core, turn, arguments, message):
    action = arguments['operation']
    identifier = arguments['workflow_id']
    operation = _operation(turn, identifier, action)
    fingerprint = digest(arguments)
    if not arguments['intent'].strip() or arguments['intent'] not in message['text']:
        raise PermissionError('请引用本轮用户明确给出的续办指令。')
    response = arguments.get('response', '')
    if response and (not response.strip() or response not in message['text']):
        raise ContractError('请直接引用本轮用户填写的补充信息。')
    attachments = {item['id']: item for item in message.get('attachments', [])}
    selected = arguments.get('attachment_ids', [])
    if set(selected) - attachments.keys():
        raise PermissionError('只能补充本轮用户实际上传的附件。')
    with core.repository.connect() as connection:
        connection.execute('BEGIN IMMEDIATE')
        row, frozen = _work(connection, turn, identifier)
        prior = _receipt(connection, operation, fingerprint)
        if prior is not None:
            return prior, False
        if _message(turn) != message:
            raise PermissionError('本轮用户消息已变化，请重新发送。')
        view = _view(connection, row, frozen)
        if view['revision'] != arguments['revision'] or action not in view['actions']:
            raise ContractError('工单状态已改变或原执行需要核对，请重新查看。')
        if action == 'continue_work' and not (selected or response):
            raise ContractError('请提供本轮补充信息或明确选择本轮附件后继续。')
        core.repository.storage.assert_executable(identifier)
        from runteams_core.work.task_inputs import copy_chat_attachment
        additions = [copy_chat_attachment(core.root, row['task_id'], turn.chat_id, attachments[key],
                                          operation_id=operation) for key in selected]
        payload = json.loads(row['payload_json'])
        payload['inputs'] = [*(payload.get('inputs') or []), *additions]
        frozen.pop('send_admitted', None)
        frozen.pop('employee_run_id', None)
        frozen['employee_followup'] = {'operation_id': operation, 'action': action, 'response': response,
                                       'attachments': [item['name'] for item in additions]}
        now = utc_now()
        connection.execute("UPDATE workflow_runs SET state='ready',available_at=?,snapshot_json=?,updated_at=? WHERE id=?",
                           (now, canonical(frozen).decode(), now, identifier))
        connection.execute("UPDATE tasks SET state='ready',payload_json=?,pipeline_snapshot_json=?,updated_at=? WHERE id=?",
                           (canonical(payload).decode(), canonical(frozen).decode(), now, row['task_id']))
        receipt = {'workflow_id': identifier, 'task_id': row['task_id'], 'action': action, 'operation_id': operation,
                   'state': 'ready', 'previous_attempt_count': view['attempt_count'],
                   'attachments': [item['name'] for item in additions]}
        core.repository.event('employee-followup:' + operation, 'employee.followup_queued',
                              {'sha256': fingerprint, 'receipt': receipt}, connection=connection)
        core.repository.event('workflow_run:' + str(identifier), 'workflow.employee_followup', receipt,
                              connection=connection)
    return receipt, True


def _execute(core, turn, arguments):
    from jsonschema import Draft202012Validator
    if (not isinstance(arguments, dict) or len(canonical(arguments)) > 16 * 1024
            or not Draft202012Validator(INPUT_SCHEMA).is_valid(arguments)):
        raise ContractError('员工工单请求无效。')
    op = arguments['operation']
    expected = {'operation'} if op == 'list' else {'operation', 'workflow_id'}
    if op == 'receipt':
        expected.add('action')
    if op in _MUTATIONS:
        expected |= {'revision', 'intent'}
    allowed = {'list': {'limit', 'before_id'}, 'continue_work': {'response', 'attachment_ids'}}.get(op, set())
    if not expected <= arguments.keys() or arguments.keys() - expected - allowed:
        raise ContractError('员工工单请求缺少必填字段或包含额外内容。')
    core._actor()
    message = _message(turn)
    if op in _MUTATIONS:
        receipt, fresh = _change(core, turn, arguments, message)
        if fresh and callable(turn.wake):
            try:
                turn.wake(receipt['workflow_id'])
            except Exception:
                logging.getLogger(__name__).exception('Employee follow-up committed but worker wake failed')
        return {'status': 'committed', 'receipt': receipt}
    with core.repository.read_snapshot() as connection:
        if op == 'list':
            limit = arguments.get('limit', 20)
            rows = connection.execute(
                _ROWS + "AND t.employee_reference=? AND w.state IN ('needs_human','blocked','failed','interrupted') "
                "AND json_extract(w.snapshot_json,'$.schema')=? "
                "AND json_type(w.snapshot_json,'$.pipeline_work') IS NULL AND w.id<? "
                "ORDER BY w.id DESC LIMIT ?",
                (employee_references.key(turn.reference), employee_work_contracts.SCHEMA,
                 arguments.get('before_id', 2**53), limit+1)).fetchall()
            items = []
            for row in rows[:limit]:
                frozen = json.loads(row['snapshot_json'])
                if _belongs(turn, frozen):
                    items.append(_view(connection, row, frozen))
            return {'items': items, 'next_before_id': rows[limit-1]['id'] if len(rows) > limit else None}
        row, frozen = _work(connection, turn, arguments['workflow_id'])
        if op == 'inspect':
            return _view(connection, row, frozen)
        receipt = _receipt(connection, _operation(turn, row['id'], arguments['action']))
        return {'status': 'unknown'} if receipt is None else {'status': 'committed', 'receipt': receipt}


def call(arguments, context):
    from runteams_core.agents.tools.agent_tool_registry import AgentToolError, AgentToolResult
    from runteams_core.work.device_work_services import current

    turn = context.get('employee_followup_turn')
    if (not isinstance(turn, _Turn) or context.get('chat_id') != turn.chat_id
            or context.get('actor_id') != principal(turn.scope)):
        raise AgentToolError('请从当前员工的主对话跟进原工单。')
    try:
        return AgentToolResult('employee_work_followup', '员工工单跟进', _execute(current(), turn, arguments))
    except (ValueError, PermissionError, OSError) as error:
        raise AgentToolError(str(error)) from error
