"""Small, read-only projection of actual work dispatched from a conversation.

The event ledger and runs remain the source of truth. No synthetic progress,
chat messages, or duplicate result storage are written by this projection.
"""
import json


def _json(value):
    try:
        return json.loads(value or '{}')
    except (TypeError, ValueError):
        return {}


def _text(value, limit=1000):
    return str(value or '').strip()[:limit]


def conversation_work(repository, chat_id=None, employee_id=None):
    """Project chat work and this employee's pending decisions into one inbox."""
    if chat_id is None and employee_id is None:
        return {'schema': 'runteams.conversation-work/v1', 'work': []}
    cards = []
    with repository.connect() as c:
        # Source ownership also recovers old dispatches whose messages only
        # stored a prose acknowledgement. Pending work is owned by the latest
        # employee run, so automation and pipeline work need no chat message.
        rows = c.execute(
            "SELECT w.id,w.state,w.created_at,w.updated_at,w.cursor_key,json_extract(w.snapshot_json,'$.employee_reference') AS employee_reference,"
            "json_extract(w.snapshot_json,'$.definition.positions') AS positions,"
            "json_extract(w.snapshot_json,'$.source.automation_id') AS automation_id,"
            "r.id AS latest_run_id,r.state AS latest_run_state,"
            "CASE WHEN w.state IN ('blocked','failed','interrupted','needs_human') THEN r.output_json END AS latest_output,"
            "CASE WHEN w.state IN ('running','waiting_retry') AND r.state='running' THEN "
            "(SELECT e.data_json FROM events e WHERE e.stream='employee_run:'||r.id "
            "AND e.type IN ('progress.reported','step.completed') ORDER BY e.id DESC LIMIT 1) END AS progress_json,"
            "CASE WHEN w.state='completed' THEN (SELECT group_concat(summary,char(10)) FROM "
            "(SELECT json_extract(done.output_json,'$.summary') AS summary FROM employee_runs done "
            "WHERE done.workflow_run_id=w.id AND done.state='completed' AND "
            "done.id=(SELECT MAX(last.id) FROM employee_runs last WHERE "
            "last.workflow_run_id=done.workflow_run_id AND last.position_key=done.position_key) "
            "AND json_extract(done.output_json,'$.summary') IS NOT NULL "
            "AND json_extract(done.output_json,'$.summary')!='' ORDER BY done.id)) END AS completed_summary,"
            "t.id AS task_id,t.title,t.employee_id,t.pipeline_id,t.trashed_at "
            "FROM workflow_runs w JOIN tasks t ON t.id=w.task_id "
            "LEFT JOIN employee_runs r ON r.id=(SELECT MAX(latest.id) FROM employee_runs latest WHERE latest.workflow_run_id=w.id) "
            "WHERE (? > 0 AND (CAST(json_extract(w.snapshot_json,'$.source.chat_id') AS INTEGER)=? OR CAST(json_extract(w.snapshot_json,'$.work_chat_id') AS INTEGER)=?)) "
            "OR (? > 0 AND w.state='needs_human' AND t.trashed_at IS NULL AND "
            "COALESCE((SELECT rel.employee_id FROM employee_runs er "
            "LEFT JOIN employee_releases rel ON rel.id=er.employee_release_id "
            "WHERE er.workflow_run_id=w.id ORDER BY er.id DESC LIMIT 1),t.employee_id)=?) "
            "ORDER BY w.id", (int(chat_id or 0), int(chat_id or 0), int(chat_id or 0),
                              int(employee_id or 0), int(employee_id or 0))).fetchall()
        for row in rows:
            item = dict(row)
            item['employee_reference']=_json(item['employee_reference']) or None
            run_id = item.pop('latest_run_id')
            run_state = item.pop('latest_run_state')
            progress = _json(item.pop('progress_json'))
            completed_summary = item.pop('completed_summary')
            state = item['state']
            result = _json(item.pop('latest_output'))
            output = result.get('output') or {}
            if not isinstance(output, dict):
                output = {}
            # If a worker just finished but orchestration has not yet advanced,
            # retain the workflow's running state until it actually completes.
            summary = _text(result.get('summary')) if state == 'completed' else ''
            detail, recovery = '', ''
            if state in ('blocked', 'failed', 'interrupted', 'needs_human'):
                detail = _text(output.get('question') if state == 'needs_human' else
                               output.get('reason') or result.get('summary') or
                               '；'.join(str(v) for v in result.get('issues') or []))
                recovery = _text(output.get('recovery'))
            human_request = None
            if state == 'needs_human' and not output.get('asset_preflight'):
                human_request = {
                    'question': _text(output.get('question'), 4000),
                    'context': output.get('context'),
                    'options': [dict(label=_text(option.get('label'), 160),
                                     description=_text(option.get('description'), 1000),
                                     recommended=bool(option.get('recommended')))
                                for option in output.get('options') or []
                                if isinstance(option, dict) and _text(option.get('label'))],
                }
            if run_id and state in ('running', 'waiting_retry') and run_state == 'running':
                detail = _text(progress.get('summary'))
            if state == 'needs_approval':
                position = next((p for p in _json(item.pop('positions')) or []
                                 if p.get('key') == item.get('cursor_key')), {})
                detail = _text(position.get('prompt') or '需要你确认后才能继续。')
            else:
                item.pop('positions', None)
            item.update(workflow_id=item.pop('id'), run_id=run_id,
                        detail=detail, recovery=recovery, summary=summary,
                        human_request=human_request)
            # A completed delivery can have multiple contributing positions.
            if state == 'completed':
                item['summary'] = _text(completed_summary)
            cards.append(item)
    return {'schema': 'runteams.conversation-work/v1', 'work': cards}
