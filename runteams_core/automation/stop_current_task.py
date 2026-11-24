"""Stop one admitted task in its original host and keep the schedule intact."""
from contextlib import nullcontext
import json
import uuid

from runteams_core.automation.device_employee_schedules import canonical
from runteams_core.foundation.contracts import ContractError

_NAMESPACE = uuid.UUID('6b08ea22-05d6-4493-946c-337d4b7b07f5')
_REASON = '用户已停止本次任务。'
_ACTIVE = ('queued', 'running', 'waiting', 'blocked', 'interrupted')


def _stop_workflow(core, kind, reference, identifier, command, *, from_schedule=False):
    from runteams_core.pipelines import pipeline_card_actions, source_pipeline_control
    with core.repository.connect() as connection:
        connection.execute('BEGIN IMMEDIATE')
        original = connection.execute(
            'SELECT w.state,w.snapshot_json,t.trashed_at,t.pipeline_id,t.employee_id FROM workflow_runs w '
            'JOIN tasks t ON t.id=w.task_id WHERE w.id=?', (identifier,)).fetchone()
        if original is None or original['trashed_at']:
            raise ContractError('原任务不可读取，请核对工作记录。')
        frozen = json.loads(original['snapshot_json'])
        if kind == 'pipeline':
            if (frozen.get('pipeline_work') or {}).get('reference') != reference:
                raise PermissionError('这项任务不属于当前智能体团队。')
        elif not from_schedule:
            from runteams_core.employees.employee_work_contracts import owns_direct_work
            if not owns_direct_work(connection, original, frozen, reference):
                raise PermissionError('这项任务不属于当前员工。')

        if original['state'] in source_pipeline_control.TERMINAL:
            return original['state']
        if kind == 'pipeline':
            stopped = pipeline_card_actions.command(core, {
                'operation_id': command, 'reference': reference, 'workflow_id': identifier,
                'expected_visit': frozen['pipeline_visit'], 'action': 'stop',
            })
            return stopped['workflow']['state']
        return core.cancel_workflow(identifier)['state']


def _occurrences(connection, reference, schedule_id):
    where = ['s.reference=?']
    params = [canonical(reference)]
    if schedule_id is not None:
        where.append('s.id=?')
        params.append(schedule_id)
    placeholders = ','.join('?' for _ in _ACTIVE)
    return connection.execute(
        'SELECT o.*,s.name,s.enabled,s.next_run_at FROM occurrences o '
        'JOIN schedules s ON s.id=o.schedule_id WHERE ' + ' AND '.join(where)
        + f' AND o.status IN ({placeholders}) ORDER BY o.id', (*params, *_ACTIVE)).fetchall()


def _target(backend, kind, row):
    if row['workflow_id']:
        return row['workflow_id']
    if kind == 'pipeline':
        return backend._receipt(backend.core(), json.loads(row['snapshot']))
    if not row['chat_id'] and row['status'] != 'queued':
        snapshot = json.loads(row['snapshot'])
        if json.loads(snapshot['reference']).get('schema') != 'runteams.local-employee-reference/1':
            result = backend.admitted(backend.controller_factory().core, row['operation_id'])
            return (result or {}).get('workflow_id')
    return None


def _ordinary_candidates(core, kind, reference, scheduled_ids):
    from runteams_core.employees.employee_work_contracts import SCHEMA, owns_direct_work

    conditions = "json_extract(w.snapshot_json,'$.schema')=?"
    if kind == 'employee':
        conditions += ' OR (t.pipeline_id IS NULL AND t.employee_id IS NOT NULL)'
    candidates = []
    with core.repository.connect() as connection:
        rows = connection.execute(
            'SELECT w.id,w.state,w.snapshot_json,t.title,t.pipeline_id,t.employee_id FROM workflow_runs w '
            "JOIN tasks t ON t.id=w.task_id WHERE w.state NOT IN ('completed','failed','canceled') "
            'AND t.trashed_at IS NULL AND (' + conditions + ') ORDER BY w.id', (SCHEMA,))
        for row in rows:
            if row['id'] in scheduled_ids:
                continue
            frozen = json.loads(row['snapshot_json'])
            if kind == 'pipeline':
                belongs = (frozen.get('pipeline_work') or {}).get('reference') == reference
            else:
                belongs = owns_direct_work(connection, row, frozen, reference)
            if belongs:
                candidates.append({'workflow_id': row['id'], 'name': row['title'], 'state': row['state']})
    return candidates


def _stop_occurrence(backend, connection, kind, reference, row, workflow_id, command):
    if workflow_id is not None:
        state = _stop_workflow(backend.controller_factory().core, kind, reference, workflow_id,
                               command, from_schedule=True)
    elif row['chat_id']:
        from runteams_core.automation.scheduled_employee_chat import outcome
        observed, _ = outcome(row['chat_id'])
        state = observed if observed in ('completed', 'failed') else 'cancelled'
    else:
        state = 'cancelled'
    stopped = state in ('canceled', 'cancelled')
    connection.execute('UPDATE occurrences SET status=?,workflow_id=?,reason=? WHERE id=?',
                       (state, workflow_id, _REASON if stopped else '', row['id']))
    return {
        'status': 'stopped' if stopped else 'already_finished', 'state': state,
        'id': row['schedule_id'], 'occurrence_id': row['id'], 'workflow_id': workflow_id,
        'chat_id': row['chat_id'], 'name': row['name'], 'enabled': bool(row['enabled']),
        'next_run_at': row['next_run_at'] or None,
    }


def execute(host, *, kind, reference, turn_key, arguments):
    if set(arguments) not in (set(), {'id'}, {'workflow_id'}) or any(
            type(value) is not int or value < 1 for value in arguments.values()):
        raise ContractError('请指定一个自动化计划编号或原任务编号。')
    backend = host.backend(kind)
    command = str(uuid.uuid5(_NAMESPACE, canonical([turn_key, kind, reference])))
    request = canonical(['stop_current', reference, arguments])

    # The pipeline gate also fences admission from the queued occurrence to the work ledger.
    if kind == 'pipeline':
        from runteams_core.automation.source_pipeline_schedules import _gate
        gate = _gate
    else:
        gate = nullcontext()
    with gate, backend.connection(write=True) as connection:
        prior = connection.execute('SELECT request,result FROM commands WHERE id=?', (command,)).fetchone()
        if prior:
            if prior['request'] != request:
                raise ContractError('本轮停止请求已处理，请重新发送消息选择其它任务。')
            result = json.loads(prior['result'])
        else:
            identifier = arguments.get('workflow_id')
            schedule_id = arguments.get('id')
            rows = [(row, _target(backend, kind, row))
                    for row in _occurrences(connection, reference, schedule_id)]
            scheduled_ids = {workflow_id for _, workflow_id in rows if workflow_id is not None}
            if identifier is not None:
                rows = [(row, workflow_id) for row, workflow_id in rows if workflow_id == identifier]
            ordinary = []
            if identifier is None and schedule_id is None:
                ordinary = _ordinary_candidates(backend.controller_factory().core, kind, reference, scheduled_ids)
            if len(rows) + len(ordinary) > 1:
                return {'status': 'multiple_active', 'items': ordinary + [
                    {'id': row['schedule_id'], 'name': row['name'], 'state': row['status'],
                     'occurrence_id': row['id'], 'workflow_id': workflow_id}
                    for row, workflow_id in rows]}
            if rows:
                row, workflow_id = rows[0]
                result = _stop_occurrence(backend, connection, kind, reference, row, workflow_id, command)
            elif identifier is not None or ordinary:
                identifier = identifier or ordinary[0]['workflow_id']
                state = _stop_workflow(backend.controller_factory().core, kind, reference, identifier, command)
                result = {'status': 'stopped' if state == 'canceled' else 'already_finished',
                          'state': state, 'workflow_id': identifier}
            else:
                result = {'status': 'no_active_task'}
            connection.execute('INSERT INTO commands VALUES(?,?,?)', (command, request, canonical(result)))

    if result['status'] == 'stopped' and result.get('occurrence_id'):
        backend.signal_occurrence_stop(result['occurrence_id'])
    return result
