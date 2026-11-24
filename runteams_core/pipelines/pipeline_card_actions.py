"""Task card actions in the original pipeline ledger, with replayable receipts."""
import copy
import json
import uuid
from datetime import datetime, timedelta, timezone

from runteams_core.authoring.creator_contracts import canonical, digest
from runteams_core.foundation.contracts import ContractError
from runteams_core.pipelines import pipeline_references, source_pipeline_control as control
from runteams_core.pipelines import source_pipeline_work as work
from runteams_core.storage.repository import utc_now


def capabilities(row, frozen, active_ids=()):
    state = row['state']
    live = (state == 'running' or bool(frozen.get('pipeline_recovery_pending')) or
            bool((frozen.get('pipeline_execution') or {}).get('active')) or
            row['id'] in active_ids and state not in ('ready', 'waiting_retry', 'paused'))
    return {'edit': state in ('ready', 'waiting_retry', 'paused') and not live,
            'pause': state in ('ready', 'waiting_retry') and not live,
            'resume': (state == 'canceled' or state == 'paused' and bool(frozen.get('pipeline_card_pause'))) and not live and not row['trashed_at'],
            'settling': state == 'canceled' and live,
            'stop': state not in control.TERMINAL and not row['trashed_at'],
            'trash': state != 'running' and not live,
            'visit': frozen['pipeline_visit']}


def queued_fields(frozen):
    return [field for field in frozen['pipeline_work']['asset']['pipeline'].get('parameters', [])
            if field.get('source') == 'user' and field.get('display', 'input') == 'input'
            and field['type'] != 'secret']


def queued_safe(row, frozen, active_ids=()):
    return (not row['trashed_at']
            and not any(frozen.get(key) for key in ('send_admitted', 'pipeline_unresolved',
                                                    'pipeline_result_correction', 'pipeline_setup_required'))
            and capabilities(row, frozen, active_ids)['edit'])


def queued_editable(connection, row, frozen, active_ids=()):
    # A new ready visit may no longer carry the completed visit's sent marker.
    return (frozen['pipeline_visit'] == 1 and queued_safe(row, frozen, active_ids)
            and connection.execute('SELECT 1 FROM employee_runs WHERE workflow_run_id=? LIMIT 1',
                                   (row['id'],)).fetchone() is None)


def _queued_inputs(row, frozen):
    # The regular attachment settings may append to the live task payload.
    return json.loads(row['payload_json']).get('inputs', frozen['pipeline_input'].get('inputs') or [])


def queued_attachments(row, frozen):
    from runteams_core.work.task_inputs import LOCAL_INPUT_REF

    for item in _queued_inputs(row, frozen):
        reference = LOCAL_INPUT_REF.fullmatch(str(item.get('ref') or ''))
        if (item.get('kind') in ('file', 'image', 'folder') and not item.get('asset_grant_id')
                and reference and int(reference[1]) == row['task_id'] and reference[2] == item.get('id')):
            yield item


def _replace_queued_attachments(row, frozen, replacements, copy_material):
    if not callable(copy_material):
        raise PermissionError('只能使用本轮对话中用户上传的附件。')
    allowed = list(queued_attachments(row, frozen))
    ids = {item['input_id'] for item in replacements}
    selected = [item for item in allowed if item['id'] in ids]
    if set(item['id'] for item in selected) != ids or len(selected) != len(ids):
        raise ContractError('既有附件已变化，或不是可以替换的本机附件。')
    copied = {item['input_id']: copy_material(row['task_id'], item['attachment_id']) for item in replacements}
    old_inputs = _queued_inputs(row, frozen)
    edited = [copied.get(item.get('id'), item) for item in old_inputs]
    audit = [{'before': item, 'after': copied[item['id']]} for item in selected]
    return edited, audit


def _edit_queued(core, connection, row, frozen, request, active_ids, copy_material):
    from runteams_core.pipelines import source_pipeline_flow as flow
    from runteams_core.pipelines.pipeline_task_configuration import validate_values

    pause = frozen.get('pipeline_card_pause') or {}
    if (row['state'] != 'paused' or pause.get('previous_state') not in ('ready', 'waiting_retry')
            or not queued_editable(connection, row, frozen, active_ids)):
        raise ContractError('请先暂缓尚未开始的原任务，再修改目标或输入。')
    allowed = queued_fields(frozen)
    keys = {field['key'] for field in allowed}
    updates = request.get('parameters', {})
    if set(updates) - keys:
        raise ContractError('只能修改已声明的普通用户输入。')
    payload = frozen['pipeline_input']
    old_values = payload.get('parameters', {})
    new_values = {**old_values, **updates}
    validate_values(allowed, {key: value for key, value in new_values.items() if key in keys})
    old_objective = payload['objective']
    objective = request.get('objective', old_objective)
    replacements = request.get('replace_attachments', [])
    if objective == old_objective and new_values == old_values and not replacements:
        raise ContractError('任务目标和输入均没有变化。')
    frozen.setdefault('initial_pipeline_input', copy.deepcopy(payload))
    attachment_changes = []
    if replacements:
        payload['inputs'], attachment_changes = _replace_queued_attachments(row, frozen, replacements, copy_material)
    elif 'inputs' in json.loads(row['payload_json']):
        payload['inputs'] = _queued_inputs(row, frozen)
    payload.update(objective=objective, parameters=new_values)
    frozen['queued_pipeline_input'] = copy.deepcopy(payload)
    role = {'context': frozen['pipeline_work'], 'package': frozen['package']}
    projected = flow.payload_for(core, connection, frozen, role)
    connection.execute('UPDATE tasks SET payload_json=? WHERE id=?',
                       (canonical(projected).decode(), row['task_id']))
    _save(core, connection, row, frozen, 'paused', row['available_at'])
    trace = {'operation_id': request['operation_id'], 'visit': frozen['pipeline_visit'],
             'parameters_before': {key: old_values[key] for key in updates if key in old_values},
             'parameters_after': updates}
    if attachment_changes:
        trace['attachment_replacements'] = attachment_changes
    if 'objective' in request:
        trace.update(objective_before=old_objective, objective_after=objective)
    core.repository.event('workflow_run:' + str(row['id']), 'workflow.queued_input_edited', trace,
                          connection=connection)


def _row(connection, ref, identifier):
    row = connection.execute('SELECT w.*,t.title,t.payload_json,t.trashed_at FROM workflow_runs w '
                             'JOIN tasks t ON t.id=w.task_id WHERE w.id=?', (identifier,)).fetchone()
    frozen = json.loads(row['snapshot_json']) if row else {}
    if (frozen.get('pipeline_work') or {}).get('reference') != ref:
        raise PermissionError('这项任务不属于当前智能体团队。')
    work.verify_context(frozen['pipeline_work'], frozen['package'])
    return row, frozen


def _save(core, connection, row, frozen, state, available=None):
    connection.execute('UPDATE workflow_runs SET state=?,snapshot_json=?,available_at=?,updated_at=? WHERE id=?',
                       (state, canonical(frozen).decode(), available, utc_now(), row['id']))
    connection.execute('UPDATE tasks SET state=?,pipeline_snapshot_json=?,updated_at=? WHERE id=?',
                       (state, canonical(frozen).decode(), utc_now(), row['task_id']))


def _restart_state(frozen, stopped):
    # Resume a confirmed human decision in place; never resend an uncertain execution.
    waiting = frozen.get('pipeline_waiting') or {}
    if not frozen.get('pipeline_unresolved'):
        if waiting.get('kind') == 'approval':
            return 'needs_approval'
        if frozen.get('pipeline_applied_result') and waiting.get('kind') == 'result' and waiting.get('state') in ('blocked', 'needs_human'):
            return waiting['state']
    if frozen.get('send_admitted') or frozen.get('pipeline_unresolved'):
        return 'interrupted'
    prior = stopped.get('previous_state', 'ready')
    return prior if prior in ('ready', 'waiting_retry', 'blocked', 'needs_human', 'needs_approval', 'interrupted') else 'ready'


def _request(data):
    fields = {'operation_id', 'reference', 'workflow_id', 'expected_visit', 'action'}
    if not isinstance(data, dict) or data.get('action') not in ('pause', 'resume', 'edit', 'edit_queued', 'stop', 'trash', 'restore'):
        raise ContractError('请选择有效的任务操作。')
    extra = {'title', 'expected_title', 'resume_after_edit'} if data['action'] == 'edit' else set()
    if data['action'] == 'edit_queued':
        extra = set(data) - fields
        if (not extra or extra - {'objective', 'parameters', 'replace_attachments'}
                or 'objective' in data and (not isinstance(data['objective'], str)
                                            or not data['objective'].strip() or len(data['objective']) > 8000)
                or 'parameters' in data and (not isinstance(data['parameters'], dict) or not data['parameters'])):
            raise ContractError('请提供有效的新目标或需要修改的任务输入。')
        if 'replace_attachments' in data:
            replacements = data['replace_attachments']
            keys = ('input_id', 'attachment_id')
            if (not isinstance(replacements, list) or not 1 <= len(replacements) <= 10
                    or any(not isinstance(item, dict) or set(item) != set(keys)
                           or any(not isinstance(item[key], str) or not 1 <= len(item[key]) <= 40 for key in keys)
                           for item in replacements)
                    or any(len({item[key] for item in replacements}) != len(replacements) for key in keys)):
                raise ContractError('一个原附件只能替换一次，每个新附件只能使用一次。')
    if set(data) != fields | extra:
        raise ContractError('任务操作参数无效。')
    try:
        if str(uuid.UUID(data['operation_id'])) != data['operation_id']:
            raise ValueError()
    except (ValueError, TypeError, AttributeError):
        raise ContractError('请沿原操作编号核对任务。') from None
    if any(type(data[k]) is not int or not 0 < data[k] < 2**53 for k in ('workflow_id', 'expected_visit')):
        raise ContractError('任务或岗位访问编号无效。')
    if data['action'] == 'edit' and (not isinstance(data['title'], str) or not data['title'].strip() or len(data['title']) > 200 or
                  not isinstance(data['expected_title'], str) or type(data['resume_after_edit']) is not bool):
        raise ContractError('请填写有效的任务名称。')
    return {**copy.deepcopy(data), 'reference': pipeline_references.checked_reference(data['reference'])}


def command(core, data, active_ids=(), *, read_only=False, guard=None, chat_fingerprint=None, copy_material=None):
    core._actor()
    request = _request(data); ref = request['reference']; identifier = request['workflow_id']
    if request['action'] == 'edit_queued' and guard is None and not read_only:
        raise PermissionError('请从当前智能体团队对话修改暂缓任务。')
    stream = 'pipeline-card-operation:' + request['operation_id']
    with core.repository.connect() as connection:
        connection.execute('BEGIN IMMEDIATE')
        row, frozen = _row(connection, ref, identifier)
        previous = connection.execute("SELECT data_json FROM events WHERE stream=? AND type='pipeline.card_committed'",
                                      (stream,)).fetchone()
        if previous:
            receipt = json.loads(previous[0])
            if receipt['request_sha256'] != digest(request):
                raise ContractError('原操作编号已用于其他内容。')
        elif read_only:
            return {'operation_id': request['operation_id'], 'status': 'unknown'}
        else:
            if guard is not None:
                guard(row, frozen)
            action = request['action']; caps = capabilities(row, frozen, active_ids)
            if frozen['pipeline_visit'] != request['expected_visit']:
                raise ContractError('任务已流转，请查看当前状态后重试。')
            if bool(row['trashed_at']) != (action == 'restore'):
                raise ContractError('任务已移入垃圾箱或已经恢复，请刷新后重试。')
            if action in ('pause', 'edit', 'edit_queued', 'resume'):
                core.repository.storage.assert_executable(identifier)
            if action == 'pause':
                if not caps['pause']:
                    raise ContractError('任务已经开始或状态已改变，不能暂停排队。')
                frozen['pipeline_card_pause'] = {'previous_state': row['state'], 'available_at': row['available_at']}
                _save(core, connection, row, frozen, 'paused')
            elif action == 'resume':
                if not caps['resume'] or control.read(core, ref, connection)['status'] != 'running':
                    raise ContractError('请先启动智能体团队，并等待原任务停止收尾后再开始。')
                if row['state'] == 'canceled':
                    paused = frozen.pop('pipeline_card_stop', {})
                    state = _restart_state(frozen, paused)
                    frozen.pop('pipeline_card_pause', None)
                    frozen.pop('pipeline_pause', None)
                else:
                    paused = frozen.pop('pipeline_card_pause')
                    # A restored execution must be reviewed through the existing recovery flow.
                    state = paused['previous_state']
                    if state not in ('ready', 'waiting_retry') or frozen.get('pipeline_unresolved'):
                        state = 'interrupted'
                _save(core, connection, row, frozen, state, paused.get('available_at'))
            elif action == 'edit_queued':
                _edit_queued(core, connection, row, frozen, request, active_ids, copy_material)
            elif action == 'edit':
                if not caps['edit'] or row['title'] != request['expected_title']:
                    raise ContractError('任务已经开始或已被修改，请保留输入并核对当前任务。')
                title = request['title'].strip()
                payload = json.loads(row['payload_json'])
                if payload.get('objective') == row['title']:
                    payload['objective'] = title
                    if frozen.get('pipeline_input', {}).get('objective') == row['title']:
                        frozen['pipeline_input']['objective'] = title
                frozen.setdefault('task', {})['title'] = title
                connection.execute('UPDATE tasks SET title=?,payload_json=?,updated_at=? WHERE id=?',
                                   (title, canonical(payload).decode(), utc_now(), row['task_id']))
                state, available = row['state'], row['available_at']
                if request['resume_after_edit']:
                    marker = frozen.get('pipeline_card_pause')
                    if not marker or marker['previous_state'] not in ('ready', 'waiting_retry'):
                        raise ContractError('当前任务需要保持暂停，请手动确认后继续。')
                    frozen.pop('pipeline_card_pause')
                    if control.read(core, ref, connection)['status'] == 'running':
                        state = 'ready'
                        available = (datetime.now(timezone.utc) + timedelta(seconds=5)).isoformat()
                    else:
                        frozen['pipeline_pause'] = {'previous_state': 'ready'}
                _save(core, connection, row, frozen, state, available)
            elif action == 'stop':
                if not caps['stop']:
                    raise ContractError('任务已经结束，请刷新查看结果。')
                frozen['pipeline_card_stop'] = {'previous_state': row['state'], 'available_at': row['available_at']}
                _save(core, connection, row, frozen, row['state'], row['available_at'])
                core.cancel_workflow(identifier)
            elif action == 'trash':
                if not caps['trash']:
                    raise ContractError('任务仍在工作，请先停止并等待收尾。')
                if row['state'] not in control.TERMINAL:
                    frozen['pipeline_card_pause'] = {'previous_state': row['state'], 'available_at': row['available_at']}
                    _save(core, connection, row, frozen, 'paused')
                connection.execute('UPDATE tasks SET trashed_at=?,updated_at=? WHERE id=?',
                                   (utc_now(), utc_now(), row['task_id']))
            else:
                if identifier in active_ids:
                    raise ContractError('原工作仍在收尾，请稍后恢复。')
                if row['state'] != 'completed':
                    prior = (frozen.get('pipeline_card_pause') or {}).get('previous_state', row['state'])
                    if frozen.get('send_admitted') or frozen.get('pipeline_unresolved'):
                        prior = 'interrupted'
                    frozen['pipeline_card_pause'] = {'previous_state': prior, 'available_at': None}
                    _save(core, connection, row, frozen, 'paused')
                connection.execute('UPDATE tasks SET trashed_at=NULL,updated_at=? WHERE id=?', (utc_now(), row['task_id']))
            receipt = {'request_sha256': digest(request), 'action': action, 'workflow_id': identifier}
            audit = dict(receipt)
            if chat_fingerprint is not None:
                audit['chat_request_sha256'] = chat_fingerprint
            core.repository.event(stream, 'pipeline.card_committed', audit, connection=connection)
        row, frozen = _row(connection, ref, identifier)
        return {'operation_id': request['operation_id'], 'status': 'committed', 'receipt': receipt,
                'workflow': {'id': identifier, 'state': row['state'], 'title': row['title'],
                             'trashed_at': row['trashed_at'], 'card_actions': capabilities(row, frozen, active_ids)}}


def trash_catalog(core):
    core._actor(); items = []
    with core.repository.read_snapshot() as connection:
        for row in connection.execute('SELECT w.*,t.title,t.trashed_at FROM workflow_runs w JOIN tasks t ON t.id=w.task_id '
                                      "WHERE t.trashed_at IS NOT NULL AND json_type(w.snapshot_json,'$.pipeline_work')='object'"):
            frozen = json.loads(row['snapshot_json'])
            items.append({'kind': 'task', 'id': row['id'], 'title': row['title'], 'trashed_at': row['trashed_at'],
                          'location': frozen['pipeline_work']['asset']['pipeline']['name'], 'can_delete': False,
                          'pipeline_reference': frozen['pipeline_work']['reference'], 'pipeline_visit': frozen['pipeline_visit'],
                          'document_count': connection.execute('SELECT COUNT(*) FROM artifacts a JOIN employee_runs r ON r.id=a.employee_run_id '
                                                               'WHERE r.workflow_run_id=? AND a.trashed_at IS NULL',
                                                               (row['id'],)).fetchone()[0]})
    return items
