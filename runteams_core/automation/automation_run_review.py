"""Read the latest actual asset execution without invoking a runner."""
from collections import Counter
import hashlib
import json
from pathlib import Path
import uuid

from runteams_core.automation.device_employee_schedules import canonical
from runteams_core.foundation.contracts import ContractError
from runteams_core.storage import device_data
from runteams_core.work import work_reports


def _occurrences(backend, reference, identifier):
    where = 's.reference=?'
    parameters = [canonical(reference)]
    if identifier is not None:
        where += ' AND s.id=?'
        parameters.append(identifier)
    with backend.connection() as connection:
        if connection is None:
            return None, None
        newest = connection.execute(
            'SELECT o.status,o.reason,s.name,o.id,o.scheduled_for FROM occurrences o '
            'JOIN schedules s ON s.id=o.schedule_id WHERE ' + where + ' ORDER BY o.id DESC LIMIT 1',
            parameters).fetchone()
        # A queued/skipped trigger with no admitted work is not an actual execution.
        latest = connection.execute(
            'SELECT o.* FROM occurrences o JOIN schedules s ON s.id=o.schedule_id WHERE ' + where +
            " AND (o.chat_id IS NOT NULL OR o.workflow_id IS NOT NULL OR o.status "
            "IN ('running','waiting','interrupted','failed','completed')) "
            "ORDER BY o.id DESC LIMIT 1", parameters).fetchone()
    return dict(newest) if newest else None, dict(latest) if latest else None


def _reference_filter(expression, reference):
    # Validate the parsed identity after the scalar pre-filter. JSON
    # member ordering differs between older work and document writers.
    fields = ('schema', 'source_id', 'employee_source', 'pipeline_source', 'id', 'rental_id')
    keys = [key for key in fields if key in reference]
    return ' AND '.join(f"json_extract({expression}, '$.{key}')=?" for key in keys), [reference[key] for key in keys]


def _latest_work(core, kind, reference):
    expression = "json_extract(w.snapshot_json,'$.pipeline_work.reference')"
    join, extra = '', ''
    if kind == 'employee':
        # Source assignments freeze the reference on the task. Earlier SDK
        # work keeps the identity in the immutable employee release.
        expression = "COALESCE(t.employee_reference,json_extract(rel.source_ref_json,'$.native_asset.employee_reference'))"
        join = 'LEFT JOIN employee_releases rel ON rel.id=r.employee_release_id '
        extra = "AND t.pipeline_id IS NULL AND json_extract(w.snapshot_json,'$.pipeline_work') IS NULL "
    clause, params = _reference_filter(expression, reference)
    with core.repository.read_snapshot() as connection:
        rows = connection.execute(
            'SELECT w.id,' + expression + ' AS reference,MIN(r.created_at) AS started_at FROM workflow_runs w '
            'JOIN tasks t ON t.id=w.task_id JOIN employee_runs r ON r.workflow_run_id=w.id ' + join +
            'WHERE t.trashed_at IS NULL AND ' + clause + ' ' + extra +
            'GROUP BY w.id ORDER BY julianday(started_at) DESC,w.id DESC', params)
        for row in rows:
            saved = json.loads(row['reference'])
            if saved == reference or kind == 'employee' and _same_employee(saved, reference):
                return dict(row)
    return None


def _same_employee(left, right):
    from runteams_core.employees.employee_references import same
    try:
        return left is not None and same(left, right)
    except (ValueError, PermissionError):
        return False


def _chat_execution(chat_id, *, operation=None, message_id=None, scheduled=False, workflow_id=None, reference=None):
    if not chat_id:
        return None
    with device_data.connect(readonly=True) as connection:
        row = connection.execute(
            'SELECT c.context_json FROM chats c JOIN device_chat_index i ON i.chat_id=c.id '
            "WHERE c.id=? AND i.deleted=0 AND c.kind='general' AND c.subject_type='employee'", (chat_id,)).fetchone()
        if not row:
            return None
        context = json.loads(row['context_json'])
        if workflow_id is not None and (context.get('employee_work') or {}).get('workflow_id') != workflow_id:
            return None
        if workflow_id is None:
            if context.get('pipeline_work') or context.get('employee_work'):
                return None
            owner = (context.get('local_employee_package') or {}).get('reference')
            owner = owner or context.get('employee_reference') or context.get('source_employee')
            if owner is not None and not _same_employee(owner, reference):
                return None
        base = "SELECT id,role,text,metadata,ts FROM chat_messages WHERE chat_id=? AND role='user'"
        if message_id is not None:
            accepted = connection.execute(base + ' AND id=?', (chat_id, message_id)).fetchone()
        else:
            accepted = connection.execute(
                base + " AND (json_extract(metadata,'$.background_work_operation')=? "
                "OR json_extract(metadata,'$.local_turn_id')=?) ORDER BY id LIMIT 1",
                (chat_id, operation, str(uuid.uuid5(uuid.NAMESPACE_URL, operation)))).fetchone()
            if accepted is None:
                # Older official hosts stored no operation marker. A dedicated
                # work chat owns its initial handoff, never a later follow-up.
                initial = connection.execute(base + ' ORDER BY id LIMIT 1', (chat_id,)).fetchone()
                if initial and (workflow_id is not None or
                                scheduled and initial['text'].startswith('这是一项已授权的定时工作，')):
                    accepted = initial
        if not accepted:
            return None
        end = connection.execute(
            base + " AND id>? AND json_extract(metadata,'$.question_request_id') IS NULL "
            "AND json_extract(metadata,'$.steer_request_id') IS NULL ORDER BY id LIMIT 1",
            (chat_id, accepted['id'])).fetchone()
        messages = connection.execute(
            'SELECT id,role,text,metadata,ts FROM chat_messages WHERE chat_id=? '
            'AND id>? AND id<? ORDER BY id DESC LIMIT 40',
            (chat_id, accepted['id'], end['id'] if end else 2**63 - 1)).fetchall()
    replies = [dict(msg, metadata=json.loads(msg['metadata'] or '{}'))
               for msg in reversed(messages) if msg['role'] in ('bot', 'assistant')]
    request_ids = [accepted['id'], *(msg['id'] for msg in messages if msg['role'] == 'user')]
    return dict(accepted, metadata=json.loads(accepted['metadata'] or '{}'), request_ids=request_ids), replies


def _reading_evidence(trace):
    reads = trace.get('knowledge_reads') or []
    if reads:
        return reads
    # Older saves can still prove a read when the native result survived
    # trace normalization. A tool name, invocation or prose claim alone cannot.
    receipts = []
    for record in trace.get('events') or []:
        event = record.get('event') or {}
        metadata = event.get('meta') or {}
        if event.get('status') not in ('completed', 'success'):
            continue
        if str(metadata.get('tool') or '').rsplit('__', 1)[-1] != 'runteams_asset_memory':
            continue
        action = (metadata.get('arguments') or {}).get('action')
        if action not in ('excerpt', 'original'):
            continue
        try:
            returned = json.loads(event.get('output') or '')
            data = returned.get('data') if isinstance(returned, dict) else None
        except (ValueError, TypeError):
            continue
        if isinstance(data, dict) and data.get('name') and (data.get('text') if action == 'excerpt' else data.get('path')):
            receipts.append({'method': action, **{key: data[key] for key in ('name', 'page', 'offset') if key in data}})
    return receipts


def _chat_evidence(execution):
    if not execution:
        return {}, []
    accepted, replies = execution
    reads = []
    result = {'accepted_message_id': accepted['id'], 'accepted_at': accepted['ts'],
              'accepted_message': accepted['text'][:12000]}
    for reply in replies:
        trace = (reply.get('metadata') or {}).get('trace') or {}
        for item in _reading_evidence(trace):
            if item not in reads and len(reads) < 30:
                reads.append(item)
        if trace.get('complete') or trace.get('cancelled') or trace.get('failed'):
            result['response_message_id'] = reply['id']
            result['response_at'] = reply['ts']
            result['saved_reply'] = reply['text'][:9000]
    return result, reads


def _document(core, identifier, name=None, *, pin=None):
    try:
        detail = core.historical_document_detail(identifier)
        if detail is None or 'content' not in detail:
            return None
        content = detail['content']
        root = detail['document_root_id']
        revision = detail['revision']
        if pin and (root != pin.get('id') or revision != pin.get('revision')
                    or hashlib.sha256(content.encode()).hexdigest() != pin.get('sha256')):
            return None
        if detail.get('content_model') == 'rich-document':
            from runteams_core.documents.rich_documents import narrative
            content = narrative(content)
    except (ContractError, OSError):
        return None
    return {'name': name or detail['name'], 'id': root, 'revision': revision,
            'artifact_id': identifier, 'kind': 'saved_document_revision',
            'revision_basis': 'accepted_submission' if pin else 'run_binding',
            'saved_at': detail.get('created_at'),
            'internal_link': f'runteams://document/{root}?revision={identifier}',
            'saved_excerpt': str(content)[:4000]}


def _file(core, artifact, *, download_supported):
    try:
        root = (Path(core.root) / 'artifacts').resolve()
        path = Path(artifact['ref']).resolve(strict=True)
        if not path.is_relative_to(root) or not path.is_file():
            return None
    except (OSError, RuntimeError):
        return None
    identifier = artifact['id']
    return {'id': identifier, 'name': artifact['name'], 'kind': 'registered_file',
            **({'download_link': f'/api/device/work/artifacts/{identifier}/content?download=1'}
               if download_supported else {})}


def _reports(core, *, reference=None, workflow_id=None, chat_id=None, request_ids=(), pins=None,
             saved_by=None, unavailable=None):
    clause = "json_extract(meta_json,'$.work_report.workflow_id')=?"
    params = [workflow_id]
    if workflow_id is None:
        clause = ("json_extract(meta_json,'$.work_report.chat_id')=? "
                  "AND json_extract(meta_json,'$.work_report.message_id') IN (SELECT value FROM json_each(?)) "
                  "AND json_extract(meta_json,'$.work_report.workflow_id') IS NULL")
        params = [chat_id, json.dumps(request_ids)]
        if saved_by:
            clause += ' AND julianday(created_at)<=julianday(?)'
            params.append(saved_by)
    with core.repository.read_snapshot() as connection:
        rows = connection.execute(
            "SELECT id,name,meta_json FROM artifacts WHERE trashed_at IS NULL "
            "AND json_extract(meta_json,'$.work_report.schema')=? "
            "AND COALESCE(json_extract(meta_json,'$.author'),'agent')='agent' "
            "AND " + clause + " ORDER BY id DESC",
            (work_reports.SCHEMA, *params))
        selected = {}
        for item in rows:
            meta = json.loads(item['meta_json'])
            if reference is not None and not _same_employee(meta['work_report']['employee_reference'], reference):
                continue
            root = meta.get('revision_of') or item['id']
            pin = (pins or {}).get(root)
            if pin and (item['id'] != pin.get('artifact_id') or
                        meta['work_report'].get('employee_run_id') != pin.get('producer')):
                continue
            if pin or len(selected) < 8:
                selected.setdefault(root, (item['id'], item['name'], pin))
            if not pins and len(selected) == 8:
                break
    reports = []
    verified = set()
    # Prefer an accepted submission over a revision inferred from a run binding.
    for identifier, name, pin in sorted(selected.values(), key=lambda item: item[2] is None):
        if len(reports) == 8 and not pin:
            break
        if saved := _document(core, identifier, name, pin=pin):
            if pin:
                verified.add(pin['id'])
            if len(reports) < 8:
                reports.append(saved)
    if unavailable is not None:
        unavailable.extend({'id': pin['id'], 'revision': pin.get('revision'), 'name': pin.get('name')}
                           for root, pin in (pins or {}).items() if root not in verified)
    return reports


def _legacy_admission(connection, workflow_id, occurrence):
    receipt = connection.execute(
        "SELECT data_json FROM events WHERE stream=? AND type='employee_schedule.admitted' ORDER BY id DESC LIMIT 1",
        ('employee-schedule:' + occurrence['operation_id'],)).fetchone()
    return receipt is not None and json.loads(receipt[0]).get('workflow_id') == workflow_id


def _legacy_work_owner(connection, workflow_id, reference):
    rows = connection.execute(
        'SELECT l.source_ref_json FROM employee_runs r JOIN employee_releases l ON l.id=r.employee_release_id '
        'WHERE r.workflow_run_id=?', (workflow_id,))
    owners = [(json.loads(row[0]).get('native_asset') or {}).get('employee_reference') for row in rows]
    return bool(owners) and all(_same_employee(owner, reference) for owner in owners)


def _workflow_evidence(core, kind, reference, workflow_id, occurrence=None, *, download_supported=False):
    pins = {}
    with core.repository.read_snapshot() as connection:
        row = connection.execute(
            'SELECT w.id,w.snapshot_json,w.state,w.task_id,w.updated_at,t.title,t.payload_json,t.pipeline_id FROM workflow_runs w '
            'JOIN tasks t ON t.id=w.task_id WHERE w.id=? AND t.trashed_at IS NULL',
            (workflow_id,)).fetchone()
        if not row:
            return None
        frozen = json.loads(row['snapshot_json'])
        if kind == 'pipeline':
            if (frozen.get('pipeline_work') or {}).get('reference') != reference:
                return None
            lineage = frozen.get('pipeline_lineage') or []
            accepted = connection.execute(
                'SELECT id,output_json FROM employee_runs WHERE workflow_run_id=? '
                'AND id IN (SELECT value FROM json_each(?)) ORDER BY id', (workflow_id, json.dumps(lineage)))
            for attempt in accepted:
                for pin in json.loads(attempt['output_json']).get('report_references') or ():
                    if isinstance(pin, dict) and type(pin.get('id')) is int:
                        pins[pin['id']] = {**pin, 'producer': attempt['id']}
        else:
            if frozen.get('pipeline_work') or row['pipeline_id'] is not None:
                return None
            if not _same_employee(frozen.get('employee_reference'), reference):
                admitted = occurrence and _legacy_admission(connection, workflow_id, occurrence)
                if not admitted and not _legacy_work_owner(connection, workflow_id, reference):
                    return None
        attempts = connection.execute(
            'SELECT id,position_key,state,input_json,output_json FROM employee_runs '
            'WHERE workflow_run_id=? ORDER BY id DESC LIMIT 12', (workflow_id,)).fetchall()
        streams = {'employee_run:' + str(attempt['id']): attempt['id'] for attempt in attempts}
        protocol_reads = {attempt_id: [] for attempt_id in streams.values()}
        events = connection.execute(
            "SELECT stream,data_json FROM events WHERE type='knowledge.source_read' "
            "AND stream IN (SELECT value FROM json_each(?)) ORDER BY id LIMIT 30",
            (json.dumps(list(streams)),))
        for event in events:
            proof = json.loads(event['data_json'])
            if proof.get('method') == 'excerpt' and proof.get('name'):
                protocol_reads[streams[event['stream']]].append({
                    key: proof[key] for key in ('method', 'name', 'page', 'offset', 'sha256',
                                                'source', 'excerpt_preview') if key in proof})
    stages, reads = [], []
    decoded = [(attempt, json.loads(attempt['input_json'])) for attempt in reversed(attempts)]
    chat_counts = Counter(inputs.get('chat_id') for _, inputs in decoded)
    for attempt, inputs in decoded:
        output = json.loads(attempt['output_json'])
        chat_id = inputs.get('chat_id')
        chat, proof = _chat_evidence(_chat_execution(chat_id if chat_counts[chat_id] == 1 else None,
            operation='employee-work:' + str(workflow_id), workflow_id=workflow_id))
        reads.extend({**item, 'position': attempt['position_key'], 'attempt_id': attempt['id']}
                     for item in [*protocol_reads[attempt['id']], *proof])
        stages.append({'position': attempt['position_key'], 'state': attempt['state'],
            'inputs': inputs.get('payload') or {key: inputs[key] for key in
                ('objective', 'skill_key', 'parameters', 'inputs', 'context') if key in inputs}, 'summary': output.get('summary'), 'issues': output.get('issues'),
            'result': output.get('output'), **chat})
    unavailable = []
    reports = _reports(core, workflow_id=workflow_id, pins=pins, unavailable=unavailable)
    with core.repository.read_snapshot() as connection:
        artifacts = connection.execute(
            'SELECT a.id,a.name,a.meta_json,a.ref FROM artifacts a LEFT JOIN employee_runs r ON r.id=a.employee_run_id '
            'WHERE a.trashed_at IS NULL AND (r.workflow_run_id=? '
            "OR json_extract(a.meta_json,'$.workflow_id')=? OR json_extract(a.meta_json,'$.workflow_run_id')=?) "
            'ORDER BY a.id DESC LIMIT 24', (workflow_id,) * 3).fetchall()
    for artifact in artifacts:
        if len(reports) >= 8:
            break
        meta = json.loads(artifact['meta_json'])
        if meta.get('work_report'):
            continue
        if core.is_document_artifact(meta, artifact['name']):
            if meta.get('author') == 'human':
                continue
            saved = _document(core, artifact['id'])
        else:
            saved = _file(core, artifact, download_supported=download_supported)
        if saved and all(item['id'] != saved['id'] for item in reports):
            reports.append(saved)
    if kind == 'pipeline':
        with core.repository.read_snapshot() as connection:
            report = connection.execute(
                "SELECT id, json_extract(meta_json,'$.pipeline_task_report.state') AS report_state, "
                "(json_extract(meta_json,'$.pipeline_task_report.state')=? OR "
                "(json_extract(meta_json,'$.pipeline_task_report.state') IS NULL "
                "AND julianday(created_at)>julianday(?))) AS matches_state "
                "FROM artifacts WHERE trashed_at IS NULL "
                "AND json_extract(meta_json,'$.source')='pipeline_task_report' "
                "AND json_extract(meta_json,'$.pipeline_task_report.task_id')=? "
                "AND json_extract(meta_json,'$.pipeline_task_report.workflow_id')=? "
                "ORDER BY COALESCE(matches_state,0) DESC, "
                "CASE WHEN matches_state AND ?='completed' THEN id END, id DESC LIMIT 1",
                (row['state'], row['updated_at'], row['task_id'], workflow_id, row['state'])).fetchone()
        if report and (saved := _document(core, report['id'])):
            reports.insert(0, {**saved, 'kind': 'saved_task_report', 'revision_basis': 'saved_task_projection',
                               'report_state': report['report_state'],
                               'final_revision': row['state'] == 'completed' and bool(report['matches_state'])})
    return {'workflow_id': workflow_id, 'title': row['title'], 'status': row['state'],
            'inputs': json.loads(row['payload_json']), 'stages': stages, 'knowledge_evidence': reads[:30],
            'deliverables': reports, **({'unavailable_report_revisions': unavailable[:8]} if unavailable else {})}


def _scheduled_evidence(core, kind, reference, run, *, download_supported=False):
    snapshot = json.loads(run['snapshot'])
    owner = snapshot.get('reference')
    if isinstance(owner, str):
        owner = json.loads(owner)
    if owner != reference:
        raise PermissionError('原触发记录不属于当前资产。')
    captured = snapshot.get('payload')
    if isinstance(captured, str):
        captured = json.loads(captured)
    result = {'source': 'automation', 'schedule_id': run['schedule_id'], 'run_id': run['id'],
              'scheduled_for': run['scheduled_for'], 'status': run['status'], 'reason': run['reason'],
              'title': snapshot.get('name') or snapshot.get('title'),
              'frozen_schedule_input': captured,
              **({'start_column_key': snapshot['start_column_key']} if 'start_column_key' in snapshot else {})}
    if not run['workflow_id'] and kind == 'pipeline' and 'operation_id' in snapshot:
        from runteams_core.pipelines.source_pipeline_work import _receipt, _request
        operation, request = _request(snapshot)
        run = {**run, 'workflow_id': _receipt(core, operation, request)}
    if run['workflow_id']:
        evidence = _workflow_evidence(core, kind, reference, run['workflow_id'], run,
                                      download_supported=download_supported)
        if evidence:
            result.update(evidence)
        else:
            result['work_record_unavailable'] = True
    elif run['chat_id']:
        execution = _chat_execution(run['chat_id'], operation=run['operation_id'], scheduled=True, reference=reference)
        chat, reads = _chat_evidence(execution)
        reports = _reports(core, reference=reference, chat_id=run['chat_id'],
                           request_ids=execution[0]['request_ids'], saved_by=chat.get('response_at')) if chat else []
        result.update(chat, knowledge_evidence=reads, deliverables=reports)
    return result


def execute(host, *, kind, reference, arguments):
    if (arguments.keys() - {'id', 'automation_only'}
            or 'automation_only' in arguments and type(arguments['automation_only']) is not bool):
        raise ContractError('验收参数无效。')
    identifier = arguments.get('id')
    if 'id' in arguments and (type(identifier) is not int or not 0 < identifier < 2**63):
        raise ContractError('请选择有效的自动化。')
    backend = host.backend(kind)
    download_supported = getattr(host, 'artifact_downloads', False)
    newest, selected = _occurrences(backend, reference, identifier)
    optional = {'latest_trigger': newest} if newest and (not selected or newest['id'] != selected['id']) else {}
    core = None
    if identifier is None and not arguments.get('automation_only'):
        core = backend.controller_factory().core
        manual = _latest_work(core, kind, reference)
        selected_at = _start_time(core, reference, selected) if selected else ''
        manual_at = manual['started_at'] if manual else ''
        # Direct chat work is discoverable through its submitted report's
        # exact accepted message. Ordinary questions are not tracked work.
        if kind == 'employee':
            direct = _direct_work(core, reference)
            if direct and _time_key(direct['accepted_at']) > max(_time_key(manual_at), _time_key(selected_at)):
                return _assessment(direct)
        if manual and (not selected or selected['workflow_id'] != manual['id']):
            if _time_key(manual_at) > _time_key(selected_at):
                result = _workflow_evidence(core, kind, reference, manual['id'],
                                            download_supported=download_supported)
                if result:
                    return _assessment({**result, 'source': 'work_card'})
    if selected is None:
        return {'status': 'no_execution_record', **optional}
    core = core or backend.controller_factory().core
    return _assessment({**_scheduled_evidence(core, kind, reference, selected,
                                              download_supported=download_supported), **optional})


def _direct_work(core, reference):
    clause, params = _reference_filter("json_extract(meta_json,'$.work_report.employee_reference')", reference)
    with core.repository.read_snapshot() as connection:
        items = connection.execute(
            "SELECT name,json_extract(meta_json,'$.work_report') AS binding FROM artifacts "
            "WHERE trashed_at IS NULL AND json_extract(meta_json,'$.work_report.schema')=? "
            "AND json_extract(meta_json,'$.work_report.workflow_id') IS NULL AND " + clause +
            " ORDER BY id DESC LIMIT 100", (work_reports.SCHEMA, *params)).fetchall()
    latest = None
    for row in items:
        item = {'name': row['name'], 'binding': json.loads(row['binding'])}
        binding = item['binding']
        if not _same_employee(binding['employee_reference'], reference):
            continue
        chat_id = binding.get('chat_id')
        message_id = binding.get('message_id')
        if binding.get('workflow_id') or not message_id:
            continue
        execution = _chat_execution(chat_id, message_id=message_id, reference=reference)
        if not execution or not execution[1]:
            continue
        accepted = execution[0]
        if (accepted['text'].startswith('这是一项已授权的定时工作，') or
                accepted['metadata'].get('background_work_operation')):
            continue
        if latest is None or _time_key(execution[0]['ts']) > _time_key(latest[0][0]['ts']):
            latest = execution, item
    if not latest:
        return None
    execution, item = latest
    chat, reads = _chat_evidence(execution)
    trace = execution[1][-1].get('metadata', {}).get('trace') or {}
    state = ('cancelled' if trace.get('cancelled') else 'failed' if trace.get('failed')
             else 'completed' if trace.get('complete') else 'unconfirmed')
    reports = _reports(core, reference=reference, chat_id=item['binding']['chat_id'],
                       request_ids=execution[0]['request_ids'], saved_by=chat.get('response_at'))
    return {**chat, 'source': 'employee_chat', 'title': item['name'], 'status': state,
            'knowledge_evidence': reads, 'deliverables': reports}


def _time_key(value):
    from runteams_core.storage.local_database import timestamp
    try:
        return timestamp(value).timestamp() if value else 0
    except (ValueError, OverflowError):
        return 0


def _start_time(core, reference, run):
    if run['workflow_id']:
        with core.repository.read_snapshot() as connection:
            row = connection.execute('SELECT COALESCE((SELECT MIN(r.created_at) FROM employee_runs r '
                'WHERE r.workflow_run_id=w.id),w.created_at) AS created_at FROM workflow_runs w WHERE w.id=?',
                (run['workflow_id'],)).fetchone()
        if row:
            return row['created_at']
    if run['chat_id']:
        accepted = _chat_execution(run['chat_id'], operation=run['operation_id'], scheduled=True, reference=reference)
        if accepted:
            return accepted[0]['ts']
    return '' if run['scheduled_for'].startswith('manual:') else run['scheduled_for']


def _assessment(result):
    methods = {item['method'] for item in result.get('knowledge_evidence', ())}
    result['knowledge_status'] = ('excerpt_recorded' if 'excerpt' in methods else
                                  'original_retrieved' if 'original' in methods else 'unverifiable')
    deliverables = result.get('deliverables', ())
    has_link = any(item.get('internal_link') or item.get('download_link') for item in deliverables)
    result['deliverable_status'] = ('openable_records' if has_link else
                                    'registered_without_link' if deliverables else 'no_openable_record_found')
    result['acceptance_requires_review'] = True
    return result
