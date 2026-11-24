"""Select real executions from the current asset's schedule, work and report records."""
from datetime import datetime
import json
import re

from runteams_core.automation import automation_run_review as review
from runteams_core.automation.device_employee_schedules import canonical
from runteams_core.foundation.contracts import ContractError
from runteams_core.work import work_reports


def _positive(value):
    return type(value) is int and 0 < value < 2**63


def _boundary(value):
    try:
        timestamp = datetime.fromisoformat(value)
        if timestamp.tzinfo is not None:
            return timestamp.timestamp()
    except (ValueError, TypeError, OverflowError):
        pass
    raise ContractError('请用包含时区的日期时间确定历史范围。')


def _scheduled_rows(backend, reference, identifier=None, run_id=None):
    predicate = ['s.reference=?']
    params = [canonical(reference)]
    for field, value in [('s.id', identifier), ('o.id', run_id)]:
        if value is not None:
            predicate.append(field + '=?')
            params.append(value)
    with backend.connection() as conn:
        if conn is None:
            return []
        rows = conn.execute('SELECT o.*,s.name FROM occurrences o JOIN schedules s ON o.schedule_id=s.id '
                            'WHERE ' + ' AND '.join(predicate) + ' ORDER BY o.id DESC', params)
        return [dict(row) for row in rows if row['workflow_id'] or row['chat_id'] or row['status'] in
                ('running','waiting','failed','completed','interrupted')]


def _work_rows(core, kind, reference):
    expression = "json_extract(w.snapshot_json,'$.pipeline_work.reference')"
    join, extra = '', ''
    if kind == 'employee':
        expression = ("COALESCE(t.employee_reference,json_extract(w.snapshot_json,'$.employee_reference'),"
                      "json_extract(rel.source_ref_json,'$.native_asset.employee_reference'))")
        join = 'LEFT JOIN employee_releases rel ON rel.id=r.employee_release_id '
        extra = " AND t.pipeline_id IS NULL AND json_extract(w.snapshot_json,'$.pipeline_work') IS NULL"
    clause, params = review._reference_filter(expression, reference)
    with core.repository.read_snapshot() as conn:
        rows = conn.execute('SELECT w.id,t.title,w.state,MIN(r.created_at) AS started,' + expression +
                            ' AS owner FROM workflow_runs w JOIN tasks t ON t.id=w.task_id '
                            'JOIN employee_runs r ON r.workflow_run_id=w.id ' + join +
                            'WHERE t.trashed_at IS NULL AND ' + clause + extra + ' GROUP BY w.id', params)
        return [dict(row) for row in rows if json.loads(row['owner']) == reference or
                kind == 'employee' and review._same_employee(json.loads(row['owner']), reference)]


def _direct(core, reference, *, selected=None):
    expr = "json_extract(meta_json,'$.work_report.employee_reference')"
    where, params = review._reference_filter(expr, reference)
    if selected:
        where += " AND json_extract(meta_json,'$.work_report.chat_id')=? AND json_extract(meta_json,'$.work_report.message_id')=?"
        params += list(selected)
    with core.repository.read_snapshot() as conn:
        rows = conn.execute("SELECT name,json_extract(meta_json,'$.work_report') AS binding FROM artifacts "
                            "WHERE trashed_at IS NULL AND json_extract(meta_json,'$.work_report.schema')=? "
                            "AND json_extract(meta_json,'$.work_report.workflow_id') IS NULL AND " + where +
                            ' ORDER BY id DESC', (work_reports.SCHEMA, *params)).fetchall()
    seen = set()
    for row in rows:
        binding = json.loads(row['binding'])
        key = binding.get('chat_id'), binding.get('message_id')
        if not all(_positive(value) for value in key) or key in seen or not review._same_employee(binding.get('employee_reference'), reference):
            continue
        seen.add(key)
        execution = review._chat_execution(key[0], message_id=key[1], reference=reference)
        if not execution or not execution[1]:
            continue
        original, replies = execution
        if original['metadata'].get('background_work_operation') or original['text'].startswith('这是一项已授权的定时工作，'):
            continue
        trace = (replies[-1].get('metadata') or {}).get('trace') or {}
        state = ('cancelled' if trace.get('cancelled') else 'failed' if trace.get('failed') else
                 'completed' if trace.get('complete') else 'unconfirmed')
        yield {'run_key': f'chat:{key[0]}:{key[1]}', 'source': 'employee_chat', 'title': row['name'],
               'started_at': original['ts'], 'status': state}, execution


def selected(host, kind, reference, run_key):
    if not isinstance(run_key, str) or not re.fullmatch(r'(?:automation|work):[1-9][0-9]{0,18}|chat:[1-9][0-9]{0,18}:[1-9][0-9]{0,18}', run_key):
        raise ContractError('请从当前资产的运行历史中选择原任务。')
    source, *raw = run_key.split(':')
    ids = [int(i) for i in raw]
    if not all(_positive(i) for i in ids):
        raise ContractError('运行编号无效。')
    backend = host.backend(kind)
    core = backend.controller_factory().core
    options = {'download_supported': getattr(host, 'artifact_downloads', False)}
    result = None
    if source == 'automation':
        rows = _scheduled_rows(backend, reference, run_id=ids[0])
        if rows:
            result = review._scheduled_evidence(core, kind, reference, rows[0], **options)
    elif source == 'work':
        result = review._workflow_evidence(core, kind, reference, ids[0], **options)
        if result:
            result['source'] = 'work_card'
    elif kind == 'employee':
        for summary, execution in _direct(core, reference, selected=ids):
            chat, reads = review._chat_evidence(execution)
            reports = review._reports(core, reference=reference, chat_id=ids[0], request_ids=execution[0]['request_ids'])
            result = {**summary, **chat, 'knowledge_evidence': reads, 'deliverables': reports}
    if not result:
        raise ContractError('在当前资产中找不到这次实际运行。请重新查看历史。')
    if result.get('workflow_id'):
        with core.repository.read_snapshot() as connection:
            row = connection.execute(
                "SELECT json_extract(snapshot_json,'$.rerun.source_run_key') FROM workflow_runs WHERE id=?",
                (result['workflow_id'],)).fetchone()
        if row and row[0]:
            result['source_run_key'] = row[0]
    return review._assessment({**result, 'run_key': run_key})


def execute(host, *, kind, reference, operation, arguments):
    if operation == 'review' and set(arguments) == {'run_key'}:
        return selected(host, kind, reference, arguments['run_key'])
    if operation != 'history' or set(arguments) - {'id','automation_only','since','until','status','query','limit','offset'}:
        raise ContractError('历史筛选条件无效。')
    identifier = arguments.get('id')
    limit, offset = arguments.get('limit', 20), arguments.get('offset', 0)
    query, status = arguments.get('query', ''), arguments.get('status', '')
    if (identifier is not None and not _positive(identifier) or type(limit) is not int or not 1 <= limit <= 100
            or type(offset) is not int or offset < 0 or type(arguments.get('automation_only', False)) is not bool
            or not isinstance(query, str) or not isinstance(status, str)):
        raise ContractError('历史筛选条件无效。')
    lower = _boundary(arguments['since']) if 'since' in arguments else None
    upper = _boundary(arguments['until']) if 'until' in arguments else None
    if lower is not None and upper is not None and lower >= upper:
        raise ContractError('结束时间必须晚于开始时间。')
    backend = host.backend(kind)
    core = backend.controller_factory().core
    rows = _scheduled_rows(backend, reference, identifier)
    items = []
    for row in rows:
        frozen = json.loads(row['snapshot'])
        items.append({'run_key': 'automation:'+str(row['id']), 'source':'automation', 'id':row['schedule_id'],
                      'title':frozen.get('name') or frozen.get('title') or row['name'], 'plan_name':row['name'],
                      'status':row['status'], 'started_at':review._start_time(core, reference, row)})
    if identifier is None and not arguments.get('automation_only'):
        assigned = {r['workflow_id'] for r in rows}
        for work in _work_rows(core, kind, reference):
            if work['id'] not in assigned:
                items.append({'run_key':'work:'+str(work['id']),'source':'work_card','title':work['title'],
                              'status':work['state'],'started_at':work['started']})
        if kind == 'employee':
            items.extend(summary for summary, _ in _direct(core, reference))
    def matches(item):
        stamp = review._time_key(item['started_at'])
        return ((lower is None or stamp >= lower) and (upper is None or stamp < upper)
                and (not status or item['status'] == status)
                and (not query or any(query.casefold() in (item.get(k) or '').casefold() for k in ('title','plan_name'))))
    items = sorted(filter(matches, items), key=lambda item: (review._time_key(item['started_at']),item['run_key']), reverse=True)
    return {'items':items[offset:offset+limit], 'total':len(items), 'next_offset': offset+limit if len(items)>offset+limit else None}
